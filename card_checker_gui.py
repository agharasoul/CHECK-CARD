#!/usr/bin/env python3

"""
Simple Tkinter GUI wrapper around card_checker.py logic.

Features:
- Select input file (.txt/.csv/.json) or paste entries
- Options: currency, retries, insecure, treat-as-payment_method
- Enter Stripe key or use STRIPE_API_KEY from environment
- Run checks and view results in a table
- Export to CSV/JSON
"""

import os
import sys
import argparse
import json
import re
import threading
import tkinter as tk
from tkinter import filedialog, messagebox, ttk
from typing import List

from card_checker import (
    read_input_file,
    read_interactive,  # not used but kept for parity
    process_cards,
    init_stripe_from_env,
    write_results_csv,
    write_results_json,
    CardInput,
    generate_card_inputs_from_bin,
    _read_json_content,
    bin_lookup,
    authorize_card_small_amount,
    CardResult,
    generate_random_named_cards,
    generate_random_card_inputs,
    mask_card_number,
)


class CardCheckerGUI(tk.Tk):
    def __init__(self, args: argparse.Namespace | None = None) -> None:
        super().__init__()
        self.title("Card Checker - Stripe Test")
        self.geometry("900x600")
        self._cli_args = args
        self.GENERATION_HARD_CAP = 5000
        self._masked_to_full = {}

        # Controls frame
        controls = ttk.Frame(self)
        controls.pack(fill=tk.X, padx=10, pady=10)

        # Input file
        self.input_path_var = tk.StringVar()
        ttk.Label(controls, text="Input file").grid(row=0, column=0, sticky="w")
        ttk.Entry(controls, textvariable=self.input_path_var, width=60).grid(row=0, column=1, padx=5)
        ttk.Button(controls, text="Browse", command=self.browse_input).grid(row=0, column=2)
        ttk.Button(controls, text="Normalize → Manual", command=self.normalize_selected_file).grid(row=0, column=4, padx=(10,0))
        self.detect_var = tk.StringVar(value="Format: –")
        ttk.Label(controls, textvariable=self.detect_var, foreground="#555").grid(row=0, column=3, padx=(10,0))

        # Stripe key
        self.key_var = tk.StringVar(value=os.environ.get("STRIPE_API_KEY", ""))
        ttk.Label(controls, text="Stripe key (sk_test_...)").grid(row=1, column=0, sticky="w")
        ttk.Entry(controls, textvariable=self.key_var, width=60, show="*").grid(row=1, column=1, padx=5)
        ttk.Button(controls, text="Use ENV", command=self.use_env_key).grid(row=1, column=2)

        # Options
        opts = ttk.Frame(controls)
        opts.grid(row=2, column=0, columnspan=3, pady=(8, 0), sticky="w")

        self.currency_var = tk.StringVar(value="usd")
        self.retries_var = tk.IntVar(value=2)
        self.insecure_var = tk.BooleanVar(value=False)
        self.pm_mode_var = tk.BooleanVar(value=False)
        self.predict_mode_var = tk.BooleanVar(value=False)
        self.live_mode_var = tk.BooleanVar(value=False)
        self.show_full_var = tk.BooleanVar(value=False)

        ttk.Label(opts, text="Currency").grid(row=0, column=0)
        ttk.Entry(opts, textvariable=self.currency_var, width=8).grid(row=0, column=1, padx=(4, 12))
        ttk.Label(opts, text="Retries").grid(row=0, column=2)
        ttk.Spinbox(opts, from_=0, to=10, textvariable=self.retries_var, width=5).grid(row=0, column=3, padx=(4, 12))
        ttk.Checkbutton(opts, text="Insecure TLS", variable=self.insecure_var).grid(row=0, column=4, padx=(0, 12))
        ttk.Checkbutton(opts, text="Treat input as payment_method id (pm_...)", variable=self.pm_mode_var).grid(row=0, column=5)
        ttk.Checkbutton(opts, text="Predict (no live transaction)", variable=self.predict_mode_var).grid(row=1, column=0, columnspan=3, sticky="w", pady=(6,0))
        ttk.Checkbutton(opts, text="Live mode ($0.50 auth; requires sk_live_)\u26a0\ufe0f", variable=self.live_mode_var).grid(row=1, column=3, columnspan=2, sticky="w", pady=(6,0))
        ttk.Checkbutton(opts, text="Show full card numbers (unsafe)", variable=self.show_full_var, command=self._on_toggle_full).grid(row=1, column=5, sticky="w", pady=(6,0))

        # Helper hint for JSON-in-.txt with nested CreditCard
        hint = ttk.Label(self, text=(
            "Hint: .txt files with JSON array of {\"CreditCard\":{...}} are auto-detected. "
            "We parse CardNumber, CVV, Exp (MM/YYYY)."
        ), foreground="#666")
        hint.pack(fill=tk.X, padx=10)

        # Manual/File mode
        mode = ttk.Frame(self)
        mode.pack(fill=tk.X, padx=10)
        self.use_manual_var = tk.BooleanVar(value=False)
        ttk.Radiobutton(mode, text="Use file", value=False, variable=self.use_manual_var).pack(side=tk.LEFT)
        ttk.Radiobutton(mode, text="Manual input", value=True, variable=self.use_manual_var).pack(side=tk.LEFT, padx=(8,0))

        # Manual input box
        manual = ttk.Frame(self)
        manual.pack(fill=tk.BOTH, expand=False, padx=10, pady=(6, 0))
        ttk.Label(manual, text="Manual entries: (name|number|month|year|cvv) or (number|month|year|cvv) or pm_... or JSON array").pack(anchor="w")
        self.manual_text = tk.Text(manual, height=6)
        self.manual_text.pack(fill=tk.X)

        # Run/Export buttons
        actions = ttk.Frame(self)
        actions.pack(fill=tk.X, padx=10, pady=6)
        ttk.Button(actions, text="Run", command=self.run_checks).pack(side=tk.LEFT)
        ttk.Button(actions, text="Stop", command=self.stop_checks).pack(side=tk.LEFT, padx=6)
        ttk.Button(actions, text="Clear", command=self.clear_all).pack(side=tk.LEFT)
        ttk.Button(actions, text="Export CSV", command=self.export_csv).pack(side=tk.LEFT, padx=6)
        ttk.Button(actions, text="Export JSON", command=self.export_json).pack(side=tk.LEFT)

        # BIN generator row
        gen = ttk.Frame(self)
        gen.pack(fill=tk.X, padx=10, pady=(0, 6))
        ttk.Label(gen, text="Generate by BIN").pack(side=tk.LEFT)
        self.gen_bin_var = tk.StringVar(value="424242")
        self.gen_count_var = tk.IntVar(value=10)
        ttk.Entry(gen, textvariable=self.gen_bin_var, width=12).pack(side=tk.LEFT, padx=(6, 4))
        ttk.Spinbox(gen, from_=1, to=9999, textvariable=self.gen_count_var, width=6).pack(side=tk.LEFT)
        ttk.Button(gen, text="Generate", command=self.generate_from_bin).pack(side=tk.LEFT, padx=6)

        # Named random generator
        gen2 = ttk.Frame(self)
        gen2.pack(fill=tk.X, padx=10, pady=(0, 6))
        ttk.Label(gen2, text="Generate Named (random)").pack(side=tk.LEFT)
        self.gen_named_count_var = tk.IntVar(value=10)
        self.gen_named_bin_var = tk.StringVar(value="")
        ttk.Spinbox(gen2, from_=1, to=9999, textvariable=self.gen_named_count_var, width=6).pack(side=tk.LEFT, padx=(6,4))
        ttk.Entry(gen2, textvariable=self.gen_named_bin_var, width=12).pack(side=tk.LEFT)
        ttk.Button(gen2, text="Generate Named", command=self.generate_named).pack(side=tk.LEFT, padx=6)

        # Pure random (no name) generator
        gen3 = ttk.Frame(self)
        gen3.pack(fill=tk.X, padx=10, pady=(0, 6))
        ttk.Label(gen3, text="Generate Random (no name)").pack(side=tk.LEFT)
        self.gen_rand_count_var = tk.IntVar(value=10)
        self.gen_rand_bin_var = tk.StringVar(value="")
        ttk.Spinbox(gen3, from_=1, to=9999, textvariable=self.gen_rand_count_var, width=6).pack(side=tk.LEFT, padx=(6,4))
        ttk.Entry(gen3, textvariable=self.gen_rand_bin_var, width=12).pack(side=tk.LEFT)
        ttk.Button(gen3, text="Generate Random", command=self.generate_random).pack(side=tk.LEFT, padx=6)

        # Scheme selection
        schemes = ttk.LabelFrame(self, text="Schemes")
        schemes.pack(fill=tk.X, padx=10, pady=(0, 6))
        self.scheme_vars = {
            "visa": tk.BooleanVar(value=True),
            "mastercard": tk.BooleanVar(value=True),
            "amex": tk.BooleanVar(value=False),
            "discover": tk.BooleanVar(value=False),
            "jcb": tk.BooleanVar(value=False),
            "diners": tk.BooleanVar(value=False),
        }
        ttk.Checkbutton(schemes, text="Visa", variable=self.scheme_vars["visa"]).pack(side=tk.LEFT)
        ttk.Checkbutton(schemes, text="MasterCard", variable=self.scheme_vars["mastercard"]).pack(side=tk.LEFT)
        ttk.Checkbutton(schemes, text="AmEx", variable=self.scheme_vars["amex"]).pack(side=tk.LEFT)
        ttk.Checkbutton(schemes, text="Discover", variable=self.scheme_vars["discover"]).pack(side=tk.LEFT)
        ttk.Checkbutton(schemes, text="JCB", variable=self.scheme_vars["jcb"]).pack(side=tk.LEFT)
        ttk.Checkbutton(schemes, text="Diners", variable=self.scheme_vars["diners"]).pack(side=tk.LEFT)

        # Verify tokens generator (pm_card_*)
        gen4 = ttk.Frame(self)
        gen4.pack(fill=tk.X, padx=10, pady=(0, 6))
        ttk.Label(gen4, text="Generate Verify (pm tokens)").pack(side=tk.LEFT)
        self.gen_verify_count_var = tk.IntVar(value=10)
        ttk.Spinbox(gen4, from_=1, to=9999, textvariable=self.gen_verify_count_var, width=6).pack(side=tk.LEFT, padx=(6,4))
        ttk.Button(gen4, text="Generate Verify", command=self.generate_verify_tokens).pack(side=tk.LEFT, padx=6)

        # Results table
        self.tree = ttk.Treeview(self, columns=(
            "masked_number","month","year","status","message","bin_bank","bin_scheme","bin_type","bin_brand","bin_country"
        ), show="headings", height=18)
        for col in self.tree["columns"]:
            self.tree.heading(col, text=col)
            self.tree.column(col, width=120 if col != "message" else 300, anchor="w")
        self.tree.pack(fill=tk.BOTH, expand=True, padx=10, pady=10)

        self.results = []
        self._stop_flag = False

        # Status bar and log
        status_frame = ttk.Frame(self)
        status_frame.pack(fill=tk.X, padx=10, pady=(0,6))
        self.status_var = tk.StringVar(value="Ready")
        ttk.Label(status_frame, textvariable=self.status_var).pack(side=tk.LEFT)

        log_frame = ttk.LabelFrame(self, text="Log")
        log_frame.pack(fill=tk.BOTH, expand=False, padx=10, pady=(0,8))
        self.log_text = tk.Text(log_frame, height=6, wrap="word")
        self.log_text.pack(fill=tk.BOTH, expand=True)

        # If CLI args provided, prefill controls and optionally auto-run
        if self._cli_args is not None:
            if getattr(self._cli_args, "input_path", None):
                self.input_path_var.set(self._cli_args.input_path)
                self._detect_input_format(self._cli_args.input_path)
            if getattr(self._cli_args, "key", None):
                self.key_var.set(self._cli_args.key)
            if getattr(self._cli_args, "currency", None):
                self.currency_var.set(self._cli_args.currency)
            if getattr(self._cli_args, "retries", None) is not None:
                try:
                    self.retries_var.set(int(self._cli_args.retries))
                except Exception:
                    pass
            if getattr(self._cli_args, "insecure", False):
                self.insecure_var.set(True)
            if getattr(self._cli_args, "pm", False):
                self.pm_mode_var.set(True)
            if getattr(self._cli_args, "predict", False):
                self.predict_mode_var.set(True)
            if getattr(self._cli_args, "live_mode", False):
                self.live_mode_var.set(True)
            if getattr(self._cli_args, "manual", False):
                self.use_manual_var.set(True)
            if getattr(self._cli_args, "manual_text", None):
                try:
                    self.manual_text.delete("1.0", tk.END)
                    self.manual_text.insert(tk.END, self._cli_args.manual_text)
                except Exception:
                    pass
            if getattr(self._cli_args, "auto_run", False):
                # Delay to allow window to initialize
                self.after(200, self.run_checks)

    def browse_input(self) -> None:
        path = filedialog.askopenfilename(title="Select input file", filetypes=[
            ("Supported", "*.txt *.csv *.json"),
            ("Text", "*.txt"),
            ("CSV", "*.csv"),
            ("JSON", "*.json"),
            ("All", "*.*"),
        ])
        if path:
            self.input_path_var.set(path)
            self._detect_input_format(path)

    def _detect_input_format(self, path: str) -> None:
        # Try to load and count entries; if it works, reflect likely format
        try:
            cards = read_input_file(path)
            count = len(cards)
            # Heuristic: if .txt and contains '{' or '[' -> JSON detected in txt
            label = "Format: "
            if path.lower().endswith('.json'):
                label += "JSON"
            elif path.lower().endswith('.csv'):
                label += "CSV"
            elif path.lower().endswith('.txt'):
                try:
                    with open(path, 'r', encoding='utf-8-sig', errors='ignore') as f:
                        head = f.read(2048)
                    if head.lstrip().startswith('{') or head.lstrip().startswith('['):
                        label += "JSON-in-.txt (auto)"
                    else:
                        label += "TXT (pipes)"
                except Exception:
                    label += "TXT"
            else:
                label += "Unknown"
            self.detect_var.set(f"{label} • Parsed: {count}")
        except Exception as e:
            self.detect_var.set(f"Format: Unknown • Error: {e}")

    def use_env_key(self) -> None:
        env_key = os.environ.get("STRIPE_API_KEY", "")
        if not env_key:
            messagebox.showwarning("Stripe key", "STRIPE_API_KEY is not set in environment")
        self.key_var.set(env_key)

    def run_checks(self) -> None:
        key = self.key_var.get().strip()
        if not key:
            messagebox.showerror("Stripe key", "Please enter Stripe secret key (sk_test_...)")
            return

        cards: List[CardInput] = []
        if self.use_manual_var.get():
            # Parse manual text area
            raw = self.manual_text.get("1.0", tk.END)
            txt = (raw or "").strip()
            if not txt:
                messagebox.showinfo("Input", "Manual input is empty.")
                return
            try:
                sniff = txt.lstrip("\ufeff\u00a0 ")
                if sniff.startswith("[") or sniff.startswith("{"):
                    # JSON content (supports nested CreditCard)
                    cards = _read_json_content(txt)
                else:
                    # Line-based entries: pm_... or number|month|year|cvv or name|number|month|year|cvv
                    for line in txt.splitlines():
                        line = line.strip()
                        if not line or line.startswith("#"):
                            continue
                        if line.startswith("pm_"):
                            cards.append(CardInput(number=line, month="12", year="2026", cvv="123"))
                            continue
                        parts = [p.strip() for p in line.split("|")]
                        if len(parts) == 5:
                            _name, number, month, year, cvv = parts
                            cards.append(CardInput(number=number, month=month, year=year, cvv=cvv))
                        elif len(parts) == 4:
                            number, month, year, cvv = parts
                            cards.append(CardInput(number=number, month=month, year=year, cvv=cvv))
                if not cards:
                    messagebox.showinfo("Input", "No valid entries parsed from Manual input.")
                    return
            except Exception as e:
                messagebox.showerror("Input error", f"Manual parse error: {e}")
                return
        else:
            path = self.input_path_var.get().strip()
            try:
                if path:
                    cards = read_input_file(path)
                else:
                    messagebox.showinfo("Input", "No file selected. Choose a file or switch to Manual input.")
                    return
            except Exception as e:
                messagebox.showerror("Input error", str(e))
                return

        # Build masked->full map for optional full display
        try:
            self._masked_to_full = {mask_card_number(c.number): c.number for c in cards}
        except Exception:
            self._masked_to_full = {}
        # Clear table
        for item in self.tree.get_children():
            self.tree.delete(item)
        self.status_var.set("Running...")
        self._append_log(f"Starting run: {len(cards)} item(s)\n")

        # Run in background thread
        threading.Thread(target=self._process_thread, args=(key, cards), daemon=True).start()

    def normalize_selected_file(self) -> None:
        """Read the selected file, lenient-parse it, and prefill Manual input in a supported format.

        Supported outputs:
        - pm_... (one per line)
        - number|month|year|cvv
        - name|number|month|year|cvv (if name present)
        """
        path = (self.input_path_var.get() or "").strip()
        if not path:
            messagebox.showinfo("Normalize", "Please select a file first.")
            return
        try:
            with open(path, "r", encoding="utf-8-sig", errors="ignore") as f:
                content = f.read()
        except Exception as e:
            messagebox.showerror("Normalize", f"Failed to read file: {e}")
            return

        try:
            lines = self._normalize_text_to_lines(content)
        except Exception as e:
            messagebox.showerror("Normalize", f"Failed to parse: {e}")
            return
        if not lines:
            messagebox.showinfo("Normalize", "No valid entries found to normalize.")
            return
        # Prefill Manual and set modes
        self.use_manual_var.set(True)
        # If any pm_ present and no raw cards, turn pm_mode on
        has_pm = any(l.strip().startswith("pm_") for l in lines)
        has_card = any("|" in l and not l.strip().startswith("#") for l in lines)
        self.pm_mode_var.set(has_pm and not has_card)
        try:
            self.manual_text.delete("1.0", tk.END)
            self.manual_text.insert(tk.END, "\n".join(lines))
        except Exception:
            pass
        self._append_log(f"Normalized {len(lines)} entries into Manual input. pm-mode={'ON' if self.pm_mode_var.get() else 'OFF'}\n")

    def _normalize_text_to_lines(self, text: str) -> list[str]:
        """Convert arbitrary text to supported lines.

        Strategy:
        1) If JSON, reuse JSON parser.
        2) Process line-by-line for pm_ and pipe-separated formats.
        3) Regex-based extraction: PAN (13-19 digits), Exp (MM/YY or MM/YYYY), CVV (3-4 digits).
        """
        s = (text or "").strip()
        if not s:
            return []

        # Try JSON first
        sniff = s.lstrip("\ufeff\u00a0 ")
        if sniff.startswith("[") or sniff.startswith("{"):
            try:
                cards = _read_json_content(s)
                if cards:
                    return [f"{c.number}|{c.month}|{c.year}|{c.cvv}" for c in cards]
            except Exception:
                pass

        out: list[str] = []
        # Quick pass: accept existing pm_ and pipe lines
        for raw in s.splitlines():
            line = raw.strip()
            if not line:
                continue
            if line.startswith("#"):
                out.append(line)
                continue
            if line.startswith("pm_"):
                out.append(line)
                continue
            parts = [p.strip() for p in line.split("|")]
            if len(parts) == 5 and parts[1].isdigit():
                # name|number|month|year|cvv
                out.append(line)
                continue
            if len(parts) == 4 and parts[0].isdigit():
                # number|month|year|cvv
                out.append(line)
                continue

        # If we already gathered some, return them
        if out:
            return out

        # Regex-based extraction per line
        # PAN: 13-19 digits (allow spaces/dashes which we strip), Exp: MM/YY or MM/YYYY, CVV: 3-4 digits
        pan_re = re.compile(r"(?<!\d)(?:\d[ -]?){13,19}(?!\d)")
        exp_re = re.compile(r"(?P<m>0[1-9]|1[0-2])[\s/.-]+(?P<y>\d{2}(?:\d{2})?)")
        cvv_re = re.compile(r"(?:(?i)cvv|cvc|code)\s*[:=]?\s*(?P<cvv>\d{3,4})|(?<!\d)(?P<plain>\d{3,4})(?!\d)")

        for raw in s.splitlines():
            t = raw.strip()
            if not t or t.startswith("#"):
                continue
            if t.startswith("pm_"):
                out.append(t)
                continue
            pan_match = pan_re.search(t)
            if not pan_match:
                continue
            pan = re.sub(r"[ -]", "", pan_match.group(0))
            exp_match = exp_re.search(t)
            cvv_match = cvv_re.search(t)
            if not exp_match or not cvv_match:
                continue
            mm = exp_match.group("m")
            yy = exp_match.group("y")
            # Normalize year to 4 digits when plausible
            if len(yy) == 2:
                yy = "20" + yy
            cvv = cvv_match.group("cvv") or cvv_match.group("plain") or ""
            if not cvv:
                continue
            out.append(f"{pan}|{mm}|{yy}|{cvv}")

        return out

    def generate_from_bin(self) -> None:
        """Generate Luhn-valid cards from BIN and prefill Manual input.

        Generated entries are plain card numbers; we ensure pm-mode is OFF.
        """
        bin_val = (self.gen_bin_var.get() or "").strip()
        try:
            count = max(1, int(self.gen_count_var.get() or 0))
        except Exception:
            count = 10
        if not bin_val or not bin_val.isdigit() or len(bin_val) < 4:
            messagebox.showerror("BIN", "Please enter a numeric BIN (at least 4 digits)")
            return
        try:
            items = generate_card_inputs_from_bin(bin_val, count)
        except Exception as e:
            messagebox.showerror("Generate", str(e))
            return

        # Switch to manual mode, turn off pm mode, and fill lines
        self.use_manual_var.set(True)
        self.pm_mode_var.set(False)
        lines = [f"{c.number}|{c.month}|{c.year}|{c.cvv}" for c in items]
        try:
            self.manual_text.delete("1.0", tk.END)
            self.manual_text.insert(tk.END, "\n".join(lines))
        except Exception:
            pass
        self._append_log(f"Generated {len(lines)} cards for BIN {bin_val}. pm-mode turned OFF.\n")

    def generate_named(self) -> None:
        """Generate random named cards (Luhn-valid) and prefill Manual input.

        Names are not required by processing; we still write a helper JSON file for the user.
        """
        try:
            count = max(1, int(self.gen_named_count_var.get() or 0))
        except Exception:
            count = 10
        if count > self.GENERATION_HARD_CAP:
            messagebox.showwarning("Generate Named", f"Count too large. Capping to {self.GENERATION_HARD_CAP}.")
            count = self.GENERATION_HARD_CAP
        opt_bin = (self.gen_named_bin_var.get() or "").strip() or None
        allowed = [k for k,v in self.scheme_vars.items() if v.get()]

        def worker():
            try:
                named = generate_random_named_cards(count, opt_bin, allowed_schemes=allowed or None)
            except Exception as e:
                self.after(0, lambda: messagebox.showerror("Generate Named", str(e)))
                return
            # Save convenience files
            try:
                with open("generated_named_cards.txt", "w", encoding="utf-8") as wf:
                    for it in named:
                        wf.write(f"{it['number']}|{it['month']}|{it['year']}|{it['cvv']}\n")
                with open("generated_named_cards.json", "w", encoding="utf-8") as jf:
                    import json as _json
                    _json.dump(named, jf, indent=2, ensure_ascii=False)
            except Exception:
                pass

            lines = [
                f"{it.get('name','')}|{it['number']}|{it['month']}|{it['year']}|{it['cvv']}"
                for it in named
            ]
            def ui_update():
                self.use_manual_var.set(True)
                self.pm_mode_var.set(False)
                try:
                    self.manual_text.delete("1.0", tk.END)
                    self.manual_text.insert(tk.END, "\n".join(lines))
                except Exception:
                    pass
                self._append_log(f"Generated {len(lines)} named cards. pm-mode turned OFF.\n")
                try:
                    preview = min(10, len(named))
                    for it in named[:preview]:
                        last4 = (it.get('number') or '')[-4:]
                        self._append_log(f"  - {it.get('name','')} (...{last4})\n")
                    if len(named) > preview:
                        self._append_log(f"  (+{len(named)-preview} more)\n")
                    self._append_log("Full names saved in generated_named_cards.json\n")
                except Exception:
                    pass
            self.after(0, ui_update)

        threading.Thread(target=worker, daemon=True).start()

    def generate_random(self) -> None:
        """Generate random cards (optionally constrained by BIN prefix) without names.

        Prefills manual input and turns pm-mode OFF.
        """
        try:
            count = max(1, int(self.gen_rand_count_var.get() or 0))
        except Exception:
            count = 10
        if count > self.GENERATION_HARD_CAP:
            messagebox.showwarning("Generate Random", f"Count too large. Capping to {self.GENERATION_HARD_CAP}.")
            count = self.GENERATION_HARD_CAP
        opt_bin = (self.gen_rand_bin_var.get() or "").strip() or None
        allowed = [k for k,v in self.scheme_vars.items() if v.get()]

        def worker():
            try:
                items = generate_random_card_inputs(count, opt_bin, allowed_schemes=allowed or None)
            except Exception as e:
                self.after(0, lambda: messagebox.showerror("Generate Random", str(e)))
                return
            # Save convenience files
            try:
                with open("generated_random_cards.txt", "w", encoding="utf-8") as wf:
                    for it in items:
                        wf.write(f"{it.number}|{it.month}|{it.year}|{it.cvv}\n")
                with open("generated_random_cards.json", "w", encoding="utf-8") as jf:
                    import json as _json
                    _json.dump([
                        {
                            "number": it.number,
                            "month": it.month,
                            "year": it.year,
                            "cvv": it.cvv,
                        } for it in items
                    ], jf, indent=2, ensure_ascii=False)
            except Exception:
                pass
            lines = [f"{it.number}|{it.month}|{it.year}|{it.cvv}" for it in items]
            def ui_update():
                self.use_manual_var.set(True)
                self.pm_mode_var.set(False)
                try:
                    self.manual_text.delete("1.0", tk.END)
                    self.manual_text.insert(tk.END, "\n".join(lines))
                except Exception:
                    pass
                self._append_log(f"Generated {len(lines)} random cards. pm-mode turned OFF.\n")
            self.after(0, ui_update)

        threading.Thread(target=worker, daemon=True).start()

    def generate_verify_tokens(self) -> None:
        """Generate pm_card_* tokens for selected schemes for verification-only tests.

        Auto-enables pm mode and fills manual input with pm ids.
        """
        try:
            count = max(1, int(self.gen_verify_count_var.get() or 0))
        except Exception:
            count = 10
        if count > self.GENERATION_HARD_CAP:
            messagebox.showwarning("Generate Verify", f"Count too large. Capping to {self.GENERATION_HARD_CAP}.")
            count = self.GENERATION_HARD_CAP
        selected = [k for k,v in self.scheme_vars.items() if v.get()]
        if not selected:
            messagebox.showinfo("Generate Verify", "Please select at least one scheme.")
            return
        scheme_to_pm = {
            "visa": "pm_card_visa",
            "mastercard": "pm_card_mastercard",
            "amex": "pm_card_amex",
            "discover": "pm_card_discover",
            "jcb": "pm_card_jcb",
            "diners": "pm_card_diners",
        }
        pool = [scheme_to_pm[s] for s in selected if s in scheme_to_pm]
        if not pool:
            messagebox.showinfo("Generate Verify", "No pm tokens available for selected schemes.")
            return
        tokens = [pool[i % len(pool)] for i in range(count)]

        # Helpful reference numbers for verification (Stripe test PANs by scheme)
        ref_numbers = {
            "visa": ("4242424242424242", "12", "2028", "123"),
            "mastercard": ("5555555555554444", "12", "2028", "123"),
            "amex": ("378282246310005", "12", "2028", "1234"),
            "discover": ("6011111111111117", "12", "2028", "123"),
            "jcb": ("3566002020360505", "12", "2028", "123"),
            "diners": ("30569309025904", "12", "2028", "123"),
        }

        # Compose manual text with commented reference lines followed by pm tokens
        header_lines = []
        for s in selected:
            if s in ref_numbers:
                n, m, y, c = ref_numbers[s]
                header_lines.append(f"# {s}: {n}|{m}|{y}|{c}")
        manual_block = "\n".join(header_lines + tokens)

        # Switch to manual and pm mode, fill lines with pm ids (and commented refs)
        self.use_manual_var.set(True)
        self.pm_mode_var.set(True)
        try:
            self.manual_text.delete("1.0", tk.END)
            self.manual_text.insert(tk.END, manual_block)
        except Exception:
            pass
        self._append_log(f"Generated {len(tokens)} pm tokens for verification. pm-mode turned ON.\n")
        for s in selected:
            if s in ref_numbers:
                n, m, y, c = ref_numbers[s]
                self._append_log(f"  Ref {s}: {n} | {m}/{y} | CVV {c}\n")

    def stop_checks(self) -> None:
        # Signal cooperative cancellation
        self._stop_flag = True
        self._append_log("Stop requested...\n")
        self.status_var.set("Stopping...")

    def clear_all(self) -> None:
        # Reset results, table, log, and status for a fresh run
        self._stop_flag = False
        self.results = []
        for item in self.tree.get_children():
            self.tree.delete(item)
        try:
            self.log_text.delete("1.0", tk.END)
        except Exception:
            pass
        self.status_var.set("Ready")

    def _process_thread(self, key: str, cards: List[CardInput]) -> None:
        try:
            os.environ["STRIPE_API_KEY"] = key
            init_stripe_from_env(max_network_retries=max(0, int(self.retries_var.get() or 0)), insecure=self.insecure_var.get())
            # Branch: predict/live/normal
            if self.predict_mode_var.get():
                self.results = []
                # Load prediction rules from predict_rules.json
                try:
                    with open("predict_rules.json", "r", encoding="utf-8") as rf:
                        rules = json.load(rf)
                except Exception:
                    rules = {}
                ecommerce_keywords = [s.lower() for s in rules.get("ecommerce_keywords", [])]
                pos_only_keywords = [s.lower() for s in rules.get("pos_only_keywords", [])]
                known_online_banks = [s.lower() for s in rules.get("known_online_banks", [])]
                known_pos_only_banks = [s.lower() for s in rules.get("known_pos_only_banks", [])]
                weights = rules.get("score_weights", {})
                w_ecomm = int(weights.get("ecommerce_keyword", 50))
                w_online_bank = int(weights.get("known_online_bank", 30))
                w_pos = int(weights.get("pos_only_keyword", -80))
                w_pos_bank = int(weights.get("known_pos_only_bank", -90))

                for card in cards:
                    if self._stop_flag:
                        break
                    try:
                        info = bin_lookup(card.number, verify_ssl=not self.insecure_var.get())
                    except Exception:
                        info = None
                    info = info or type("X", (), {"scheme":"","card_type":"","brand":"","country_name":"","bank":"","country":""})()
                    blob = " ".join([
                        (getattr(info, "scheme", "") or ""),
                        (getattr(info, "card_type", "") or ""),
                        (getattr(info, "brand", "") or ""),
                        (getattr(info, "country_name", "") or ""),
                    ]).lower()
                    bank_l = (getattr(info, "bank", "") or "").lower()
                    score = 0
                    if any(k in blob for k in ecommerce_keywords):
                        score += w_ecomm
                    if any(k in bank_l for k in known_online_banks):
                        score += w_online_bank
                    if any(k in blob for k in pos_only_keywords):
                        score += w_pos
                    if any(k in bank_l for k in known_pos_only_banks):
                        score += w_pos_bank
                    score = max(0, min(100, score))
                    if score >= 70:
                        pred_status = "Likely Active"
                    elif score >= 40:
                        pred_status = "Possibly Active"
                    else:
                        pred_status = "Unlikely Active"
                    masked = mask_card_number(card.number)
                    r = CardResult(
                        masked_number=masked,
                        month=card.month,
                        year=card.year,
                        status=pred_status,
                        message=None,
                        bin_bank=getattr(info, "bank", None),
                        bin_scheme=getattr(info, "scheme", None),
                        bin_type=getattr(info, "card_type", None),
                        bin_brand=getattr(info, "brand", None),
                        bin_country=getattr(info, "country", None),
                        prediction_score=score,
                        prediction_status=pred_status,
                    )
                    self.results.append(r)
                    self._on_progress(r)
                self.status_var.set("Completed")
            elif self.live_mode_var.get():
                # Require live key
                ak = os.environ.get("STRIPE_API_KEY", "")
                if not ak.startswith("sk_live_"):
                    raise RuntimeError("Live mode requires STRIPE_API_KEY starting with sk_live_")
                self.results = []
                for card in cards:
                    if self._stop_flag:
                        break
                    pm_id = card.number if (self.pm_mode_var.get() and str(card.number).startswith("pm_")) else None
                    if self.pm_mode_var.get() and not pm_id:
                        r = CardResult(masked_number=card.number, month=card.month, year=card.year, status="Error", message="Not a pm_ id", bin_bank=None, bin_scheme=None, bin_type=None, bin_brand=None, bin_country=None)
                        self.results.append(r)
                        self._on_progress(r)
                        continue
                    status_code, message = authorize_card_small_amount(card, amount=50, currency=self.currency_var.get().strip() or "usd", payment_method_id=pm_id)
                    status_out = "Active (Live OK)" if status_code == "ok" else ("Inactive" if status_code == "declined" else "Error")
                    masked = mask_card_number(card.number)
                    r = CardResult(masked_number=masked, month=card.month, year=card.year, status=status_out, message=message, bin_bank=None, bin_scheme=None, bin_type=None, bin_brand=None, bin_country=None)
                    self.results.append(r)
                    self._on_progress(r)
                self.status_var.set("Completed")
            else:
                self.results = process_cards(
                    cards,
                    currency=self.currency_var.get().strip() or "usd",
                    verify_ssl=not self.insecure_var.get(),
                    treat_as_payment_method=self.pm_mode_var.get(),
                    on_progress=self._on_progress,
                    should_stop=lambda: self._stop_flag,
                )
        except Exception as e:
            self.after(0, lambda: messagebox.showerror("Processing error", str(e)))
            self.after(0, lambda: self.status_var.set("Error"))
            return

        # Populate table in UI thread
        def populate():
            self.status_var.set("Stopped" if self._stop_flag else "Completed")
            self._stop_flag = False
        self.after(0, populate)

    def _on_progress(self, r) -> None:
        # Called from worker thread; use after() for UI safety
        def ui():
            display_number = r.masked_number
            try:
                if self.show_full_var.get():
                    display_number = self._masked_to_full.get(r.masked_number, r.masked_number)
            except Exception:
                pass
            self._append_log(f"{r.status} {display_number} - {(r.message or '')}\n")
            # Add row as-it-goes
            self.tree.insert("", tk.END, values=(
                display_number, r.month, r.year, r.status, (r.message or ""),
                (r.bin_bank or ""), (r.bin_scheme or ""), (r.bin_type or ""), (r.bin_brand or ""), (r.bin_country or "")
            ))
        self.after(0, ui)

    def _on_toggle_full(self) -> None:
        # Re-render current table according to checkbox
        try:
            all_items = self.tree.get_children()
            current_rows = [self.tree.item(i, "values") for i in all_items]
            # values: [masked/full, month, year, status, message, bin_bank, bin_scheme, bin_type, bin_brand, bin_country]
            self.tree.delete(*all_items)
            for row in current_rows:
                masked_or_full = row[0]
                display_number = masked_or_full
                if self.show_full_var.get():
                    display_number = self._masked_to_full.get(masked_or_full, masked_or_full)
                new_row = (display_number,) + tuple(row[1:])
                self.tree.insert("", tk.END, values=new_row)
        except Exception:
            pass

    def _append_log(self, text: str) -> None:
        try:
            self.log_text.insert(tk.END, text)
            self.log_text.see(tk.END)
        except Exception:
            pass

    def export_csv(self) -> None:
        if not self.results:
            messagebox.showinfo("Export", "No results to export.")
            return
        path = filedialog.asksaveasfilename(defaultextension=".csv", filetypes=[("CSV", "*.csv")])
        if not path:
            return
        try:
            write_results_csv(path, self.results)
            messagebox.showinfo("Export", f"Saved: {path}")
        except Exception as e:
            messagebox.showerror("Export error", str(e))

    def export_json(self) -> None:
        if not self.results:
            messagebox.showinfo("Export", "No results to export.")
            return
        path = filedialog.asksaveasfilename(defaultextension=".json", filetypes=[("JSON", "*.json")])
        if not path:
            return
        try:
            write_results_json(path, self.results)
            messagebox.showinfo("Export", f"Saved: {path}")
        except Exception as e:
            messagebox.showerror("Export error", str(e))


def parse_cli(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Card Checker GUI")
    parser.add_argument("--input", dest="input_path", help="Path to input file (.txt/.csv/.json)")
    parser.add_argument("--key", dest="key", help="Stripe secret key sk_test_... (overrides env)")
    parser.add_argument("--currency", default="usd")
    parser.add_argument("--retries", type=int, default=2)
    parser.add_argument("--insecure", action="store_true")
    parser.add_argument("--pm", action="store_true", help="Treat input as payment_method ids")
    parser.add_argument("--auto-run", action="store_true", help="Start and immediately run checks")
    parser.add_argument("--manual", action="store_true", help="Start GUI in Manual input mode")
    parser.add_argument("--manual-text", help="Prefill manual input text (use \n for newlines)")
    return parser.parse_args(argv)


def main() -> None:
    args = parse_cli(sys.argv[1:])
    if args.key:
        os.environ["STRIPE_API_KEY"] = args.key
    # Convert escaped \n to actual newlines for prefill convenience
    if getattr(args, "manual_text", None):
        try:
            args.manual_text = args.manual_text.replace("\\n", "\n")
        except Exception:
            pass
    app = CardCheckerGUI(args)
    app.mainloop()


if __name__ == "__main__":
    main()


