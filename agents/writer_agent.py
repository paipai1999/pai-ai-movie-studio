import json
import math
import os
import re
from brain.memory import MovieState
from brain.gemini_client import call_gemini
from brain.prompts import (
    FULL_MOVIE_TRANSLATION_SYSTEM_PROMPT,
    MOVIE_RECAP_STORYTELLER_SYSTEM_PROMPT,
    HARDSUB_BURMESE_TRANSLATION_SYSTEM_PROMPT,
)
from brain import config as cfg
from brain.burmese_utils import (
    replace_numbers_with_burmese,
    transliterate_english_acronyms,
    sanitize_burmese_narration,
)


class WriterAgent:
    def __init__(
        self,
        language: str = "burmese",
        max_blocks: int | None = None,
        script_engine: str = "recap",
    ):
        self.language = language
        self.max_blocks = max_blocks or (int(os.getenv("MAX_BLOCKS")) if os.getenv("MAX_BLOCKS") else None)
        self.script_engine = (script_engine or os.getenv("SCRIPT_ENGINE") or "recap").lower()

    def get_system_prompt_for_style(self, style: str) -> str:
        s = str(style or "").lower().strip()
        if s in ["persona", "character", "kinship"]:
            return HARDSUB_BURMESE_TRANSLATION_SYSTEM_PROMPT
        elif s == "recap":
            return MOVIE_RECAP_STORYTELLER_SYSTEM_PROMPT
        else:
            return FULL_MOVIE_TRANSLATION_SYSTEM_PROMPT

    def _get_system_prompt(self, state: MovieState) -> str:
        active_style = getattr(state, "translation_style", None) or self.script_engine or "recap"
        return self.get_system_prompt_for_style(active_style)

    # ─────────────────────────────────────────────────────
    # PUBLIC: generate_script (Full Movie Dialogue Translation / Movie Recap Storyteller)
    # ─────────────────────────────────────────────────────
    def generate_script(self, state: MovieState, movie_path: str = "") -> MovieState:
        """
        Dual Narration Engine:
        1. 'recap' (Default): True Myanmar Movie Recap Storyteller persona with conversational
           sentence endings, narrative bridges, and dramatic timing.
        2. 'translate': 1:1 Complete Spoken Dialogue Translation & Dubbing.
        """
        engine_label = "RECAP STORYTELLER" if self.script_engine == "recap" else "1:1 TRANSLATE DUBBING"
        print(f"[*] WriterAgent: Generating {engine_label} SCRIPT (Lang: {self.language}, Engine: {self.script_engine.upper()})...")

        if not state.transcript:
            print("[!] WriterAgent: No transcript found. Skipping dialogue translation.")
            return state

        config_data = cfg.load_config()
        gemini_cfg = config_data.get("gemini", {})
        gemini_key = gemini_cfg.get("api_keys") or os.getenv("GEMINI_API_KEYS") or os.getenv("GEMINI_API_KEY") or ""
        models_dict = gemini_cfg.get("models", {})
        model_workhorse = models_dict.get("workhorse", "gemini-3.5-flash-lite")

        # 1. Extract, clean, and smooth Whisper dialogue segments
        # Ensures 100% full coverage while eliminating micro-fragments, repetitive stutters, and unnatural breaks
        import re

        def _clean_transcript_line(t: str) -> str:
            t = re.sub(r'\[.*?\]|\(.*?\)', '', t)
            t = re.sub(r'\.{2,}', '.', t)
            t = re.sub(r'-{2,}', ' ', t)
            t = re.sub(r'\s+', ' ', t).strip()
            return t

        whisper_hallucinations = {
            "thank you for watching", "thanks for watching", "please subscribe",
            "subscribe to my channel", "bye bye", "see you next time", "subtitles by",
            "subtitles", "thank you.", "bye.", "you"
        }

        initial_segments = []
        for i, seg in enumerate(state.transcript):
            if isinstance(seg, dict):
                t_start = float(seg.get("start", 0.0) or 0.0)
                t_end = float(seg.get("end", t_start + 2.0) or (t_start + 2.0))
                text = str(seg.get("text", "")).strip()
            else:
                t_start = float(getattr(seg, "start", 0.0) or 0.0)
                t_end = float(getattr(seg, "end", t_start + 2.0) or (t_start + 2.0))
                text = str(getattr(seg, "text", "")).strip()

            cleaned = _clean_transcript_line(text)
            if not cleaned or len(cleaned) <= 1 or t_end <= t_start:
                continue
            if cleaned.lower().rstrip('.!') in whisper_hallucinations:
                continue

            seg_dur = t_end - t_start
            # Split only very long monologue segments (> 7.0s) at full sentence boundaries
            if seg_dur > 7.0 and re.search(r'(?<!\bMr)(?<!\bDr)(?<!\bMs)(?<!\bMrs)(?<!\bSt)(?<!\be\.g)(?<!\bi\.e)[.!?]\s+[A-Z]', cleaned):
                parts = [p.strip() for p in re.split(r'(?<=[.!?])\s+(?=[A-Z])', cleaned) if p.strip()]
                if len(parts) > 1:
                    total_chars = sum(len(p) for p in parts)
                    c_start = t_start
                    for p_idx, p in enumerate(parts):
                        prop = len(p) / total_chars if total_chars > 0 else (1.0 / len(parts))
                        c_dur = seg_dur * prop
                        c_end = t_end if (p_idx == len(parts) - 1) else (c_start + c_dur)
                        initial_segments.append({
                            "start_sec": round(c_start, 2),
                            "end_sec": round(c_end, 2),
                            "text": p
                        })
                        c_start = c_end
                    continue

            initial_segments.append({
                "start_sec": round(t_start, 2),
                "end_sec": round(t_end, 2),
                "text": cleaned
            })

        if not initial_segments:
            print("[!] WriterAgent: No valid dialogue text found in transcript.")
            return state

        # Pass 1: Deduplicate Whisper stuttering tokens (e.g. repeated word fragments)
        deduped = []
        for seg in initial_segments:
            if not deduped:
                deduped.append(seg)
                continue
            prev = deduped[-1]
            prev_words = [w.lower().strip('.,!?\'"') for w in prev["text"].split() if w.strip('.,!?\'"')]
            curr_words = [w.lower().strip('.,!?\'"') for w in seg["text"].split() if w.strip('.,!?\'"')]
            if not curr_words:
                continue
            # If the entire segment is just 1-2 words that were already spoken at the end of prev
            if len(curr_words) <= 2 and all(w in prev_words[-3:] for w in curr_words):
                prev["end_sec"] = max(prev["end_sec"], seg["end_sec"])
                continue
            if seg["text"].lower().strip('.,!?') == prev["text"].lower().strip('.,!?'):
                prev["end_sec"] = max(prev["end_sec"], seg["end_sec"])
                continue
            deduped.append(seg)

        # Pass 2: Merge micro-fragments (< 2.2s or < 4 words) into cohesive complete thoughts
        MIN_DUR = 2.2
        MIN_WORDS = 4
        MAX_GAP = 1.8

        merged_segments = []
        s_i = 0
        n_deduped = len(deduped)
        while s_i < n_deduped:
            curr = deduped[s_i]
            words = curr["text"].split()
            dur = curr["end_sec"] - curr["start_sec"]
            is_frag = (dur < MIN_DUR) or (len(words) < MIN_WORDS)

            # Try forward merge if next segment is close
            if is_frag and (s_i + 1 < n_deduped):
                nxt = deduped[s_i + 1]
                gap_forward = round(nxt["start_sec"] - curr["end_sec"], 2)
                if gap_forward <= MAX_GAP:
                    joiner = " " if curr["text"].endswith(('.', '!', '?', ',')) else ", "
                    nxt["text"] = (curr["text"].rstrip('.!?') + joiner + nxt["text"]).strip()
                    nxt["start_sec"] = curr["start_sec"]
                    s_i += 1
                    continue

            # If cannot forward-merge, try backward merge into previous segment
            if is_frag and merged_segments:
                prev = merged_segments[-1]
                gap_back = round(curr["start_sec"] - prev["end_sec"], 2)
                if gap_back <= MAX_GAP:
                    joiner = " " if prev["text"].endswith(('.', '!', '?', ',')) else ", "
                    prev["text"] = (prev["text"].rstrip('.!?') + joiner + curr["text"]).strip()
                    prev["end_sec"] = curr["end_sec"]
                    s_i += 1
                    continue

            merged_segments.append(curr)
            s_i += 1

        audio_source = getattr(state, "vocals_path", "") or getattr(state, "audio_path", "")
        if audio_source and not os.path.exists(audio_source):
            audio_source = ""
        vid_path = movie_path or getattr(state, "movie_path", "")
        if vid_path and not os.path.exists(vid_path):
            vid_path = ""

        def _extract_keyframe_b64(vpath: str, t_sec: float, max_dim: int = 480):
            if not vpath or not os.path.exists(vpath):
                return None
            try:
                import cv2
                import base64
                cap = cv2.VideoCapture(vpath)
                if not cap.isOpened():
                    return None
                fps = cap.get(cv2.CAP_PROP_FPS) or 25.0
                cap.set(cv2.CAP_PROP_POS_FRAMES, int(t_sec * fps))
                ret, frame = cap.read()
                cap.release()
                if not ret or frame is None:
                    return None
                h, w = frame.shape[:2]
                if max(h, w) > max_dim:
                    scale = max_dim / max(h, w)
                    frame = cv2.resize(frame, (int(w * scale), int(h * scale)), interpolation=cv2.INTER_AREA)
                ret, buffer = cv2.imencode('.jpg', frame, [cv2.IMWRITE_JPEG_QUALITY, 65])
                if ret:
                    return base64.b64encode(buffer).decode('utf-8')
            except Exception:
                pass
            return None

        raw_segments = []
        for idx, seg in enumerate(merged_segments):
            dur = round(max(MIN_DUR, seg["end_sec"] - seg["start_sec"]), 2)
            max_chars = max(24, int(dur * 11.0))
            acoustic_gender = "unknown"
            if audio_source and os.path.exists(audio_source):
                try:
                    from agents.audio_agent import AudioAgent
                    acoustic_gender = AudioAgent.detect_pitch_gender(audio_source, seg["start_sec"], seg["end_sec"])
                except Exception:
                    acoustic_gender = "unknown"

            raw_segments.append({
                "id": idx + 1,
                "start_sec": seg["start_sec"],
                "end_sec": seg["end_sec"],
                "duration_sec": dur,
                "max_chars": max_chars,
                "acoustic_gender": acoustic_gender,
                "text": seg["text"]
            })

        if not raw_segments:
            print("[!] WriterAgent: No valid dialogue text found after smoothing.")
            return state

        total_count = len(raw_segments)
        if self.max_blocks and self.max_blocks > 0 and total_count > self.max_blocks:
            raw_segments = raw_segments[:self.max_blocks]
            total_count = len(raw_segments)
            print(f"[*] WriterAgent: Limited to MAX_BLOCKS={self.max_blocks} dialogue lines.")

        print(f"[*] WriterAgent: Found {total_count} sentence-level dialogue segments to translate (100% full coverage).")

        # 2. Batch dialogue lines (20 per batch) for fast, reliable Gemini translation
        BATCH_SIZE = 20
        all_translated = []

        for b_idx in range(0, total_count, BATCH_SIZE):
            batch = raw_segments[b_idx:b_idx + BATCH_SIZE]
            batch_num = (b_idx // BATCH_SIZE) + 1
            total_batches = math.ceil(total_count / BATCH_SIZE)
            print(f"[*] WriterAgent: Translating Batch {batch_num}/{total_batches} ({len(batch)} dialogues)...")

            # Extract 1-2 representative keyframes per batch for visual diarization & context
            batch_images = []
            if vid_path and os.path.exists(vid_path):
                sample_indices = [len(batch) // 2] if len(batch) <= 5 else [0, len(batch) // 2]
                for s_i in sample_indices:
                    mid_t = (batch[s_i]["start_sec"] + batch[s_i]["end_sec"]) / 2.0
                    b64_frame = _extract_keyframe_b64(vid_path, mid_t)
                    if b64_frame:
                        batch_images.append(b64_frame)

            active_style = getattr(state, "translation_style", None) or self.script_engine or "recap"
            active_style = str(active_style).lower().strip()
            if active_style in ["persona", "character", "kinship"]:
                sys_prompt = HARDSUB_BURMESE_TRANSLATION_SYSTEM_PROMPT
                batch_prompt = (
                    f"Target Language: {self.language.upper()}\n"
                    f"Movie Title: {state.movie_name}\n"
                    f"Translate each dialogue line below with 100% faithful precision into colloquial {self.language.title()} enforcing strict Male (ကျနော်/ခင်ဗျာ), Female (ကျွန်မ/ရှင်), and Child (သား/သမီး) personas:\n"
                    f"{json.dumps(batch, ensure_ascii=False, indent=2)}\n\n"
                    f"Output a JSON array where each object has: id, narration, start_sec, end_sec, emotion, character, gender (\"male\" or \"female\")."
                )
            elif active_style == "recap":
                sys_prompt = MOVIE_RECAP_STORYTELLER_SYSTEM_PROMPT
                batch_prompt = (
                    f"Target Language: {self.language.upper()}\n"
                    f"Movie Title: {state.movie_name}\n"
                    f"Write suspenseful, captivating MOVIE RECAP STORYTELLER narration for each scene below in natural colloquial {self.language.title()}.\n"
                    f"CRITICAL RECAP REQUIREMENTS:\n"
                    f"1. TRUE RECAP STORYTELLER STYLE: Speak directly as an engaging Myanmar YouTube movie recap narrator ('ဒီဇာတ်လမ်းမှာတော့...', '...ခဲ့တာပေါ့ဗျာ'). DO NOT do dry literal 1:1 sentence dubbing.\n"
                    f"2. CONVERSATIONAL RECAP ENDINGS: Every line MUST end with natural storytelling particles: '...ခဲ့တာပေါ့ဗျာ', '...နေခဲ့ပါတယ်', '...လိုက်ရတာပါ', '...သွားခဲ့ရတယ်', '...ဖြစ်နေတာပါ', '...ကြတာပေါ့', '...ရတော့တာပါ'. ❌ FORBIDDEN: Blunt chopped endings like '...တယ်', '...တာ', '...ဘူး'.\n"
                    f"3. DYNAMIC NARRATIVE TRANSITIONS: Bridge scenes naturally using recap connectors ('ဇာတ်လမ်းအစမှာတော့...', 'အဲဒီအချိန်မှာပဲ...', 'မထင်မှတ်ထားဘဲ...', 'ဒီလိုနဲ့...', 'ကြည့်လိုက်တဲ့အခါမှာတော့...').\n"
                    f"4. STRICT CHARACTER BUDGET & DURATION MATCH: Each line's `narration` MUST STRICTLY STAY UNDER its given `max_chars` limit (Burmese TTS rate is ~10 chars/sec) so audio finishes cleanly within `duration_sec` seconds! Keep phrasing punchy and exciting.\n"
                    f"5. CLEAN BURMESE TEXT: Transliterate names and English loanwords phonetically. Never output foreign characters.\n\n"
                    f"{json.dumps(batch, ensure_ascii=False, indent=2)}\n\n"
                    f"Output a JSON array where each object has: id, narration, start_sec, end_sec, emotion, character, gender (\"male\" or \"female\")."
                )
            else:
                sys_prompt = FULL_MOVIE_TRANSLATION_SYSTEM_PROMPT
                batch_prompt = (
                    f"Target Language: {self.language.upper()}\n"
                    f"Movie Title: {state.movie_name}\n"
                    f"Translate EVERY SINGLE movie dialogue sentence below into natural colloquial {self.language.title()} for professional dubbing.\n"
                    f"CRITICAL REQUIREMENTS:\n"
                    f"1. STRICT 1:1 TRANSLATION: Translate every single item completely. DO NOT summarize, merge, or drop any sentence.\n"
                    f"2. Translate all character names, places, events, and plot points accurately without leaving anything out.\n"
                    f"3. STRICT CHARACTER BUDGET & DURATION MATCH: Each translation's `narration` MUST STRICTLY STAY UNDER its given `max_chars` limit (Burmese TTS rate is ~11 chars/sec). Keep sentences punchy, concise, and direct so the spoken narration finishes precisely within `duration_sec` seconds! NEVER write long verbose sentences that exceed `max_chars`!\n"
                    f"4. MULTIMODAL SPEAKER DIARIZATION & GENDER ACCURACY: Observe the visual frame context and 'acoustic_gender' hint ('male', 'female', or 'unknown') for each dialogue. Determine the speaker's true 'gender' ('male' or 'female'), 'character' name/role, and 'emotion' ('normal', 'excited', 'angry', 'sad', 'scared', 'intense'). If 'acoustic_gender' is 'female' or the visual frame shows a female speaking, mark gender as 'female'!\n"
                    f"5. NATURAL CINEMATIC FLOW: Avoid repetitive sentence endings (do NOT repeat identical words like 'ပေါ့', 'ပါ', 'တယ်' in consecutive lines). Write natural storytelling movie recap dialogue.\n\n"
                    f"{json.dumps(batch, ensure_ascii=False, indent=2)}\n\n"
                    f"Output a JSON array where each object has: id, narration, start_sec, end_sec, emotion, character, gender (\"male\" or \"female\")."
                )

            batch_translated = None
            if gemini_key:
                try:
                    raw_res, used_model = call_gemini(
                        sys_prompt,
                        batch_prompt,
                        gemini_key,
                        model_workhorse,
                        temperature=0.3,
                        max_tokens=4096,
                        response_mime_type="application/json",
                        images=batch_images if batch_images else None,
                    )
                    batch_translated = self._parse_script(raw_res)
                except Exception as e:
                    print(f"[WARN] WriterAgent: Batch {batch_num} Gemini call failed: {e}")

            if not batch_translated:
                batch_translated = []

            # Map translated items by id
            trans_map = {}
            for item in batch_translated:
                if isinstance(item, dict) and "id" in item:
                    try:
                        trans_map[int(item["id"])] = item
                    except (ValueError, TypeError):
                        pass

            # Ensure EVERY item in the batch is preserved with target language translation
            for seg in batch:
                s_id = seg["id"]
                if s_id in trans_map and (trans_map[s_id].get("narration") or trans_map[s_id].get("burmese") or trans_map[s_id].get("translation")):
                    item = trans_map[s_id]
                    narration = str(item.get("narration") or item.get("burmese") or item.get("translation") or "").strip()
                    emotion = str(item.get("emotion", "normal")).strip()
                    gender = str(item.get("gender") or item.get("speaker_gender") or "male").strip().lower()
                    if gender in ["child", "boy"]:
                        gender = "female" if "သမီး" in narration else "male"
                    elif gender not in ["male", "female"]:
                        gender = "male"
                    character = str(item.get("character", "Narrator")).strip()
                    if getattr(self, "language", "burmese").lower() in ["burmese", "mm", "myanmar"]:
                        try:
                            narration = replace_numbers_with_burmese(narration)
                            narration = transliterate_english_acronyms(narration)
                            narration = sanitize_burmese_narration(narration)
                        except Exception:
                            pass
                else:
                    # Individual line fallback if dropped by Gemini
                    narration = seg["text"]
                    emotion = "normal"
                    gender = seg.get("acoustic_gender") if seg.get("acoustic_gender") in ("male", "female") else "male"
                    character = "Narrator"
                    if gemini_key:
                        try:
                            if self.script_engine == "recap":
                                fb_sys = f"You are a master movie recap storyteller into natural colloquial {self.language.title()} with lively storytelling endings."
                                fb_prompt = f"Write natural storyteller movie recap narration in {self.language.title()} for this scene:\n'{seg['text']}'\nReturn ONLY the recap narration as plain text, without quotes or meta explanation."
                            else:
                                fb_sys = f"You are a professional movie dubbing translator into natural colloquial {self.language.title()}."
                                fb_prompt = f"Translate this dialogue into natural colloquial {self.language.title()}:\n'{seg['text']}'\nReturn ONLY the translation as plain text, without quotes or meta explanation."

                            line_res, _ = call_gemini(
                                fb_sys,
                                fb_prompt,
                                gemini_key,
                                model_workhorse,
                                temperature=0.3,
                                max_tokens=512,
                                response_mime_type="text/plain"
                            )
                            clean_line = line_res.strip().strip('"').strip("'").strip()
                            if clean_line and not any(bad in clean_line.lower() for bad in ["json", "```", "here is", "here's"]):
                                if getattr(self, "language", "burmese").lower() in ["burmese", "mm", "myanmar"]:
                                    try:
                                        clean_line = replace_numbers_with_burmese(clean_line)
                                        clean_line = transliterate_english_acronyms(clean_line)
                                        clean_line = sanitize_burmese_narration(clean_line)
                                    except Exception:
                                        pass
                                narration = clean_line
                        except Exception:
                            pass

                # Record character profile in state for downstream multi-voice & SEO consistency
                if character and character not in state.speaker_profiles:
                    state.speaker_profiles[character] = {
                        "gender": gender,
                        "emotions": [emotion]
                    }
                elif character and emotion not in state.speaker_profiles[character].get("emotions", []):
                    state.speaker_profiles[character]["emotions"].append(emotion)

                all_translated.append({
                    "scene_id": str(s_id),
                    "narration": narration,
                    "start_sec": seg["start_sec"],
                    "end_sec": seg["end_sec"],
                    "gender": gender,
                    "character": character,
                    "emotion": emotion,
                    "visual_cue": f"Dialogue ({seg['start_sec']}s - {seg['end_sec']}s): {seg['text'][:40]}..."
                })

        # 3. Action Narration Bridge: Bridge silent or long action gaps (> 18s)
        if gemini_key:
            all_translated = self._bridge_action_narration(all_translated, state, gemini_key, model_workhorse)

        state.generated_script = all_translated
        print(f"[OK] WriterAgent: 100% Full Movie Dialogue Translation complete! Total {len(all_translated)} dialogue lines dubbed.")
        return state

    def _bridge_action_narration(self, blocks: list, state: MovieState, gemini_key: str, model: str) -> list:
        """
        Bridges silent or long action gaps (> 18s) with engaging movie recap narration in the target language.
        Turns quiet combat, chase, or suspense sequences into a lively, continuous story recap.
        """
        if not blocks or not gemini_key:
            return blocks

        config_data = cfg.load_config()
        action_cfg = config_data.get("action_narration", {})
        if not action_cfg.get("enabled", True):
            return blocks

        min_gap = float(action_cfg.get("min_gap_sec", 18.0))
        blocks = sorted(blocks, key=lambda x: float(x.get("start_sec", 0.0)))
        
        bridge_candidates = []
        first_start = float(blocks[0].get("start_sec", 0.0))
        if first_start >= min_gap:
            bridge_candidates.append({
                "pos_idx": 0,
                "gap_start": 2.0,
                "gap_end": first_start - 1.0,
                "gap_dur": first_start - 3.0,
                "prev_text": "Movie opening introduction",
                "next_text": blocks[0].get("narration", "")[:60]
            })

        for i in range(len(blocks) - 1):
            curr_end = float(blocks[i].get("end_sec", 0.0))
            next_start = float(blocks[i+1].get("start_sec", 0.0))
            gap = next_start - curr_end
            if gap >= min_gap:
                bridge_candidates.append({
                    "pos_idx": i + 1,
                    "gap_start": curr_end + 1.5,
                    "gap_end": next_start - 1.5,
                    "gap_dur": gap,
                    "prev_text": blocks[i].get("narration", "")[:80],
                    "next_text": blocks[i+1].get("narration", "")[:80]
                })

        if not bridge_candidates:
            return blocks

        print(f"[*] WriterAgent (Action Narration): Detected {len(bridge_candidates)} silent/action sequences (> {min_gap}s). Generating recap narration...")

        new_blocks = list(blocks)
        added_count = 0
        for cand in bridge_candidates[:10]:
            prompt = (
                f"Movie Title: {state.movie_name}\n"
                f"In this movie recap, there is an action or suspense sequence lasting {int(cand['gap_dur'])} seconds without dialogue.\n"
                f"Previous dialogue: '{cand['prev_text']}'\n"
                f"Upcoming dialogue: '{cand['next_text']}'\n\n"
                # FIX-BUG4: Dynamic language for bridge narration
                f"Write a short, engaging 1-2 sentence narrator recap in natural colloquial {self.language.title()} "
                f"describing what happens in the scene or setting up the tension.\n"
                f"RULES:\n"
                f"- Max 20 words.\n"
                f"- Conversational recap style.\n"
                f"- NO formal written language.\n"
                f"- Return ONLY the narration text, no JSON, no quotes, no explanation."
            )
            try:
                res, _ = call_gemini(
                    "You are an expert movie recap channel narrator.",
                    prompt,
                    gemini_key,
                    model=model,
                    temperature=0.4,
                    max_tokens=150,
                    response_mime_type="text/plain",  # FIX-BUG3: plain text, not JSON
                )
                txt = res.strip().strip('"').strip("'").strip()
                if txt.startswith("{") or txt.startswith("["):
                    try:
                        data = json.loads(txt)
                        if isinstance(data, dict):
                            for k in ["narration", "recap", "text", "summary", "recaps"]:
                                if k in data:
                                    val = data[k]
                                    txt = val[0] if isinstance(val, list) and val else str(val)
                                    break
                        elif isinstance(data, list) and data:
                            txt = str(data[0])
                    except Exception:
                        pass
                txt = txt.strip().strip('"').strip("'").strip()
                if txt and len(txt) > 4:
                    if getattr(self, "language", "burmese").lower() in ["burmese", "mm", "myanmar"]:
                        try:
                            txt = replace_numbers_with_burmese(txt)
                            txt = transliterate_english_acronyms(txt)
                            txt = sanitize_burmese_narration(txt)
                        except Exception:
                            pass
                    bridge_dur = min(cand["gap_dur"] - 2.0, 5.5)
                    b_start = round(cand["gap_start"], 2)
                    b_end = round(b_start + max(bridge_dur, 3.0), 2)
                    new_blocks.append({
                        "scene_id": f"action_bridge_{added_count+1}",
                        "narration": txt,
                        "start_sec": b_start,
                        "end_sec": b_end,
                        "gender": "male",
                        "character": "Narrator",
                        "emotion": "excited",
                        "visual_cue": f"Action Scene ({b_start}s - {b_end}s)"
                    })
                    added_count += 1
            except Exception as e:
                print(f"[WARN] WriterAgent: Action narration failed for gap at {cand['gap_start']}s: {e}")

        new_blocks.sort(key=lambda x: float(x.get("start_sec", 0.0)))
        print(f"[OK] WriterAgent (Action Narration): Successfully bridged {added_count} action scenes with lively commentary!")
        return new_blocks


    # ─────────────────────────────────────────────────────
    # JSON PARSER
    # ─────────────────────────────────────────────────────
    def _parse_script(self, raw: str):
        """Robustly extracts a JSON array from LLM output."""
        clean = re.sub(r'^```(?:json)?\s*|\s*```$', '', raw, flags=re.MULTILINE).strip()
        clean = re.sub(r',\s*([\]}])', r'\1', clean)

        # Strategy 1: Direct parse
        try:
            return self._normalise(json.loads(clean))
        except json.JSONDecodeError:
            pass

        # Strategy 2: Slice from first [ to last ]
        for open_c, close_c in [('[', ']'), ('{', '}')]:
            start = clean.find(open_c)
            end   = clean.rfind(close_c)
            if start != -1 and end > start:
                try:
                    return self._normalise(json.loads(clean[start:end + 1]))
                except json.JSONDecodeError:
                    pass

        # Strategy 3: Strip trailing extra brackets
        clean_brackets = re.sub(r'\]\s*\]+$', ']', clean)
        try:
            return self._normalise(json.loads(clean_brackets))
        except json.JSONDecodeError:
            pass

        # Strategy 4: Regex full array (greedy match from first [ to last ])
        m = re.search(r'\[.*\]', clean_brackets, re.DOTALL)
        if m:
            try:
                return self._normalise(json.loads(m.group()))
            except json.JSONDecodeError:
                pass
                
        # Strategy 5: Stack-based JSON extraction (most robust)
        start_idx = clean.find('[')
        if start_idx != -1:
            stack = 0
            for i in range(start_idx, len(clean)):
                if clean[i] == '[': stack += 1
                elif clean[i] == ']': stack -= 1
                if stack == 0:
                    try:
                        return self._normalise(json.loads(clean[start_idx:i+1]))
                    except json.JSONDecodeError:
                        break

        # Strategy 6: Plain paragraphs → blocks (rejecting JSON artifacts or meta chatter)
        raw_paragraphs = [p.strip() for p in raw.split('\n\n') if len(p.strip()) > 10]
        valid_paragraphs = []
        for p in raw_paragraphs:
            p_lower = p.lower()
            if any(bad in p_lower for bad in ["```", "json", "here is", "here's", "i have", "translate"]):
                continue
            valid_paragraphs.append(p)
        if valid_paragraphs:
            print(f"[*] WriterAgent: Extracted {len(valid_paragraphs)} paragraphs from plain text.")
            return [
                {
                    "scene_id":   str(i + 1),
                    "narration":  p,
                    "visual_cue": "Continue narration",
                }
                for i, p in enumerate(valid_paragraphs)
            ]

        return None

    def _normalise(self, data) -> list:
        """Ensure the script is a list of dicts with string values.
        CRITICAL: Preserve start_sec and end_sec so video sync is never broken.
        """
        if not data:
            return []
        if isinstance(data, dict):
            data = [data]
        elif not isinstance(data, list):
            return []

        result = []
        for i, item in enumerate(data):
            if isinstance(item, str):
                narration = item
                block_id = i + 1
                item = {}
            elif isinstance(item, dict):
                narration = (
                    item.get("narration")
                    or item.get("translation")
                    or item.get("myanmar_text")
                    or item.get("burmese_text")
                    or item.get("text")
                    or ""
                )
                block_id = item.get("id", item.get("scene_id", i + 1))
            else:
                continue

            if not str(narration).strip():
                continue
            block = {
                "id":         block_id,
                "scene_id":   str(block_id),
                "narration":  str(narration).strip(),
                "visual_cue": str(item.get("visual_cue", "Dialogue")),
            }
            # Preserve exact timestamps — these drive character lip-sync placement
            if "start_sec" in item:
                try: block["start_sec"] = float(item["start_sec"])
                except (ValueError, TypeError): pass
            if "end_sec" in item:
                try: block["end_sec"] = float(item["end_sec"])
                except (ValueError, TypeError): pass
            if "character" in item and item["character"]:
                block["character"] = str(item["character"]).strip()
            if "speaker" in item and item["speaker"]:
                block["speaker"] = str(item["speaker"]).strip()
                if "character" not in block:
                    block["character"] = block["speaker"]
            elif "character" in block:
                block["speaker"] = block["character"]
            if "gender" in item:
                block["gender"] = str(item["gender"])
            if "emotion" in item:
                block["emotion"] = str(item["emotion"])
            result.append(block)
        return result
