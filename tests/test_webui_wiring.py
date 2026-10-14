"""Phase 6 tests: WebUI wiring + VRAM cleanup + review prefill (static + unit).

webui.py cannot be imported on system python (torch/hubert at main import),
so UI structure is verified via AST (deterministic, no gradio needed).
Seams: lyrics.asr.unload_models(device=...), webui.free_lyrics_models,
review accordion click graph.
"""
import ast
import pathlib
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))

WEBUI = Path("src") / "webui.py"


def tree():
    return ast.parse(WEBUI.read_text(encoding="utf-8"))


def funcs(t):
    return {n.name: n for n in ast.walk(t) if isinstance(n, ast.FunctionDef)}


class TestASRUnloadDevice(unittest.TestCase):
    def test_unload_cuda_only(self):
        from lyrics import asr as A
        A._MODEL_CACHE[("tiny", "cpu")] = object()
        A._MODEL_CACHE[("base", "cuda")] = object()
        try:
            A.unload_models(device="cuda")
            self.assertIn(("tiny", "cpu"), A._MODEL_CACHE)
            self.assertNotIn(("base", "cuda"), A._MODEL_CACHE)
        finally:
            A._MODEL_CACHE.clear()

    def test_unload_all_by_default(self):
        from lyrics import asr as A
        A._MODEL_CACHE[("tiny", "cpu")] = object()
        try:
            A.unload_models()
            self.assertEqual(dict(A._MODEL_CACHE), {})
        finally:
            A._MODEL_CACHE.clear()


class TestFreeLyricsModels(unittest.TestCase):
    def test_helper_exists_top_level_never_raises(self):
        t = tree()
        top = [n.name for n in t.body if isinstance(n, ast.FunctionDef)]
        self.assertIn("free_lyrics_models", top)
        src = ast.get_source_segment(WEBUI.read_text(encoding="utf-8"),
                                     funcs(t)["free_lyrics_models"])
        self.assertIn("unload_models", src)
        self.assertIn("try", src)
        self.assertIn("except", src)

    def test_cover_flow_frees_before_pipeline(self):
        src = WEBUI.read_text(encoding="utf-8")
        node = funcs(tree())["run_cover_webui"]
        body = ast.get_source_segment(src, node)
        self.assertIn("free_lyrics_models", body)
        self.assertIn("song_cover_pipeline", body)
        self.assertLess(body.index("free_lyrics_models"),
                        body.index("song_cover_pipeline"))


class TestLyricsUIWiring(unittest.TestCase):
    def test_three_optional_accordions(self):
        t = tree()
        titles = [c.args[0].value for c in ast.walk(t)
                  if isinstance(c, ast.Call)
                  and getattr(getattr(c, "func", None), "attr", "") == "Accordion"
                  and c.args and isinstance(c.args[0], ast.Constant)]
        for want in ("Lyrics Checker (optional)",
                     "Post-RVC Analysis (optional)",
                     "Lyric Review (optional)"):
            self.assertTrue(any(want in x for x in titles), want)

    def test_all_check_buttons_wired(self):
        src = WEBUI.read_text(encoding="utf-8")
        for btn in ("lyrics_btn.click", "postrvc_btn.click",
                    "review_start.click", "review_preview_btn.click",
                    "review_save.click", "review_discard.click",
                    "review_apply.click", "review_confirm.click",
                    "review_revert.click", "review_picker.change"):
            self.assertIn(btn, src, btn)

    def test_review_start_outputs_include_edit_prefill(self):
        # Start populates detail + edit box for the first item (no dead step).
        t = tree()
        clicks = [c for c in ast.walk(t) if isinstance(c, ast.Call)
                  and getattr(getattr(c, "func", None), "attr", "") == "click"]
        found = False
        for c in clicks:
            kw = {k.arg: k.value for k in c.keywords}
            outs = kw.get("outputs")
            if isinstance(outs, ast.List) and len(outs.elts) == 6:
                names = set()
                for e in outs.elts:
                    if isinstance(e, ast.Name):
                        names.add(e.id)
                if {"review_state", "review_status", "review_items",
                        "review_picker", "review_detail", "review_edit"} <= names:
                    found = True
        self.assertTrue(found, "review_start must output 6 inc. edit prefill")

    def test_handler_arity_matches_click_wiring(self):
        # Every .click/.change(handler, inputs=[...], outputs=[...]) must
        # agree with the handler signature and return-tuple sizes. Single
        # (non-tuple) returns count as 1. Catches silent Gradio miswiring.
        t = tree()
        fns = {n.name: n for n in ast.walk(t)
               if isinstance(n, ast.FunctionDef)}
        checked = 0
        for c in ast.walk(t):
            if not isinstance(c, ast.Call):
                continue
            func = getattr(c, "func", None)
            if not (isinstance(func, ast.Attribute)
                    and func.attr in ("click", "change")):
                continue
            if not c.args or not isinstance(c.args[0], ast.Name):
                continue
            name = c.args[0].id
            if name not in fns or name in ("run_cover_webui",):
                continue
            kw = {k.arg: k.value for k in c.keywords}
            handler = fns[name]
            if isinstance(kw.get("inputs"), ast.List):
                # Gradio injects `progress` automatically; it is not in inputs.
                params = [a.arg for a in handler.args.args
                          if a.arg != "progress"]
                self.assertEqual(len(kw["inputs"].elts), len(params), name)
            if isinstance(kw.get("outputs"), ast.List):
                helper_sizes = {}
                for h in fns.values():
                    hs = set()
                    for r in ast.walk(h):
                        if isinstance(r, ast.Return) and isinstance(
                                r.value, ast.Tuple):
                            hs.add(len(r.value.elts))
                    if hs:
                        helper_sizes[h.name] = hs
                sizes = set()
                for r in ast.walk(handler):
                    if not isinstance(r, ast.Return):
                        continue
                    v = r.value
                    if isinstance(v, ast.Tuple):
                        sizes.add(len(v.elts))
                    elif (isinstance(v, ast.Call)
                          and isinstance(v.func, ast.Name)
                          and v.func.id in helper_sizes):
                        sizes |= helper_sizes[v.func.id]
                    else:
                        sizes.add(1)
                self.assertTrue(sizes, name)
                for s in sizes:
                    self.assertEqual(s, len(kw["outputs"].elts), name)
                checked += 1
        self.assertGreaterEqual(checked, 10)

    def test_no_button_without_handler(self):
        t = tree()
        defined = set(funcs(t))
        for name in ("run_lyrics_check", "run_postrvc_check",
                     "run_review_start", "run_review_detail",
                     "run_review_apply", "run_review_confirm",
                     "run_review_revert", "run_review_preview",
                     "run_review_save", "run_review_discard",
                     "run_cover_webui"):
            self.assertIn(name, defined, name)


class TestMotionContract(unittest.TestCase):
    """Refinement motion is CSS-only, capped, and escapable (static checks)."""

    def test_keyframes_and_hooks_exist(self):
        src = WEBUI.read_text(encoding="utf-8")
        for token in ("@keyframes cyber-arrive",
                      "@keyframes cyber-pulse-glow",
                      ".cyber-arrive",
                      ".lrc-report .lrc-item",
                      "prefers-reduced-motion"):
            self.assertIn(token, src, token)

    def test_no_layout_property_animation(self):
        import re
        head = WEBUI.read_text(encoding="utf-8")
        head = head[head.index("CYBER_PLAYER_HEAD"):]
        animated = re.findall(r"transition:\s*([^;]+);", head)
        bad_props = {"width", "height", "top", "left", "margin", "padding"}
        for decl in animated:
            props = {p.strip().split(" ")[0] for p in decl.split(",")}
            self.assertTrue(props.isdisjoint(bad_props), decl)

    def test_playing_state_wired(self):
        src = WEBUI.read_text(encoding="utf-8")
        self.assertIn("setCyberPlaying", src)
        self.assertIn("card_' + cid", src)
        self.assertIn('id="card_{cid}"', src)

class TestRedesignContract(unittest.TestCase):
    """Redesign skill audit locks: characterful type, radius system,
    borderless rows, and a closed palette (static checks)."""

    def test_font_stack_has_character(self):
        src = WEBUI.read_text(encoding="utf-8")
        self.assertIn('"IBM Plex Sans"', src)
        self.assertIn("Segoe UI Variable", src)
        self.assertIn("tabular-nums", src)

    def test_radius_system(self):
        src = WEBUI.read_text(encoding="utf-8")
        head = src[src.index("CYBER_PLAYER_HEAD"):]
        self.assertIn("border-radius: 12px", head)
        self.assertNotIn("border-radius: 3px", head)

    def test_mismatch_rows_borderless(self):
        import sys as _sys
        _sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))
        from lyrics import compare_texts
        html = compare_texts("hello world", "hello word", "en").to_html()
        self.assertIn('class="lrc-item"', html)
        import re
        start = html.index('<div class="lrc-item"')
        row_tag = html[start:html.index(">", start)]
        self.assertIsNone(re.search(r"(?:^|[;\"'])border\s*:", row_tag))

    def test_palette_locked(self):
        import re
        allowed = {"8d8d8d", "0f62fe", "fa4d56", "4589ff", "ffffff",
                   "393939", "c6c6c6", "161616", "f4f4f4", "42be65",
                   "262626", "0353e9", "002d9c", "525252", "6f6f6f",
                   "f1c21b", "000000"}
        for path in ("src/webui.py", "src/lyrics/report.py"):
            txt = pathlib.Path(path).read_text(encoding="utf-8")
            found = set(m.lower() for m in re.findall(r"#([0-9a-fA-F]{3,8})\b", txt))
            self.assertTrue(found <= allowed, f"{path}: {found - allowed}")

class TestReskinHooks(unittest.TestCase):
    """Visible reskin uses Gradio-official hooks (elem_id/elem_classes),
    never guessed internal selectors."""

    def test_hero_hook(self):
        src = WEBUI.read_text(encoding="utf-8")
        self.assertIn('elem_id="aig-hero"', src)

    def test_cta_hook(self):
        import re
        src = WEBUI.read_text(encoding="utf-8")
        line = next(l for l in src.splitlines() if "generate_btn = gr.Button" in l)
        self.assertIn("aig-cta", line)

    def test_accordion_hooks(self):
        src = WEBUI.read_text(encoding="utf-8")
        n = sum(1 for l in src.splitlines()
                if "gr.Accordion(" in l and "aig-acc" in l)
        self.assertGreaterEqual(n, 6)

    def test_spring_motion_no_banned_easing(self):
        src = WEBUI.read_text(encoding="utf-8")
        head = src[src.index("CYBER_PLAYER_HEAD"):]
        self.assertIn("cubic-bezier(0.32,0.72,0,1)", head)
        self.assertNotIn("ease-in-out", head)
        self.assertIn("accent-color: #0f62fe", head)
        self.assertIn("#aig-hero", head)
        self.assertIn(".aig-cta", head)

    def test_no_banned_fonts(self):
        src = WEBUI.read_text(encoding="utf-8")
        for banned in ("Roboto", "Arial", "Open Sans", "Helvetica", "Inter,"):
            self.assertNotIn(banned, src)

    def test_report_hooks_rendered(self):
        import sys as _sys
        _sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))
        from lyrics import compare_texts
        html = compare_texts("hello world", "hello word", "en").to_html()
        self.assertIn('class="lrc-report cyber-arrive"', html)
        self.assertIn('class="lrc-item"', html)
        self.assertIn("animation-delay:", html)


class TestInteractiveHighEnd(unittest.TestCase):
    """Redesign + high-end skills: pointer spotlight, EQ bars, magnetic CTA,
    hero drift, mount entrances. Static checks; no browser needed."""

    def _head(self):
        src = WEBUI.read_text(encoding="utf-8")
        return src[src.index("CYBER_PLAYER_HEAD"):]

    def test_spotlight_hook(self):
        head = self._head()
        self.assertIn("--mx", head)
        self.assertIn("--my", head)
        self.assertIn("mousemove", head)
        self.assertIn(".cyber-player-card, .lrc-report", head)

    def test_eq_bars(self):
        import sys as _sys
        _sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))
        head = self._head()
        self.assertIn("@keyframes eq-bounce", head)
        self.assertIn(".playing", head)
        self.assertIn("animation-play-state", head)
        self.assertIn('class="cyb-eq"', head)

    def test_magnetic_cta(self):
        head = self._head()
        self.assertIn(".aig-cta", head)
        self.assertIn("matchMedia", head)
        self.assertIn("prefers-reduced-motion", head)

    def test_hero_drift_transform_only(self):
        import re
        head = self._head()
        self.assertIn("@keyframes hero-drift", head)
        m = re.search(r"@keyframes hero-drift\s*\{(.*?)\n\}", head, re.S)
        self.assertIsNotNone(m)
        self.assertNotIn("background-position", m.group(1))

    def test_mount_entrance_no_scroll_listener(self):
        head = self._head()
        self.assertIn(".aig-acc", head)
        self.assertNotIn("addEventListener('scroll'", head)
        self.assertNotIn('addEventListener("scroll"', head)

    def test_no_layout_property_animation(self):
        import re
        head = self._head()
        for decl in re.findall(r"transition:\s*([^;]+);", head):
            props = {p.strip().split(" ")[0] for p in decl.split(",")}
            self.assertTrue(props.isdisjoint(
                {"width", "height", "top", "left", "margin", "padding"}), decl)


if __name__ == "__main__":
    unittest.main()
