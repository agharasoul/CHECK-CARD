# Card Checker (Stripe Test) · چک‌کننده کارت استرایپ

Validate and score cards in Stripe test mode via CLI & Tkinter GUI.
BIN lookup · Luhn generation by BIN · Prediction mode · Optional live micro‑auth.

ابزار تست کارت با استرایپ (CLI + GUI)
شامل BIN Lookup، ساخت شماره‌های معتبر لوهِن از روی BIN، پیش‌بینی اکتیون بودن، و میکرو اتورایز لایو (اختیاری).

---

## ✨ Features | امکانات
- CLI + GUI (Tkinter)
- Inputs: TXT (`number|month|year|cvv`), CSV, JSON, یا ورودی تعاملی
- Stripe Test (PaymentIntent + manual capture) و پشتیبانی از `pm_card_...`
- BIN Lookup از `binlist`
- Mask: `first6******last4`
- Outputs: `results.csv`, `results.json`
- رنگ ترمینال: سبز (OK/Likely)، زرد (Possibly)، قرمز (Declined/Unlikely/Error)
- Luhn Generation: `--generate-bin`
- Prediction Mode: `--predict` (قوانین در `predict_rules.json`)
- Live Mode (اختیاری): `--live-mode` با `sk_live_...` و کنسل فوری

---

## ⚙️ Install | نصب
```bash
pip install -U stripe requests
```
PowerShell (تنظیم کلید):
```powershell
setx STRIPE_API_KEY "sk_test_..."   # یا sk_live_...
```
سپس ترمینال جدید باز کنید.

---

## 🧪 CLI (English)
- Help:
  ```bash
  python card_checker.py -h
  ```
- Test with file:
  ```bash
  python card_checker.py -i cards.txt
  ```
- Using test PaymentMethods:
  ```bash
  python card_checker.py -i pm_cards.txt --pm
  ```
- Generate Luhn by BIN:
  ```bash
  python card_checker.py --generate-bin 412199 20
  ```
- Predict (no transactions):
  ```bash
  python card_checker.py --generate-bin 412199 10 --predict
  ```
- Live micro‑auth (requires `sk_live_`):
  ```bash
  python card_checker.py -i cards.txt --live-mode
  ```
Notes: For quick OK in test, prefer `pm_card_visa` with `--pm`. Stripe blocks raw card data by default. See https://docs.stripe.com/testing

## 🧪 CLI (فارسی)
- راهنما:
  ```bash
  python card_checker.py -h
  ```
- تست با فایل:
  ```bash
  python card_checker.py -i cards.txt
  ```
- استفاده از PaymentMethodهای تست:
  ```bash
  python card_checker.py -i pm_cards.txt --pm
  ```
- ساخت کارت‌های لوهِن از BIN:
  ```bash
  python card_checker.py --generate-bin 412199 20
  ```
- پیش‌بینی بدون تراکنش:
  ```bash
  python card_checker.py --generate-bin 412199 10 --predict
  ```
- میکرو اتورایز لایو (نیازمند `sk_live_`):
  ```bash
  python card_checker.py -i cards.txt --live-mode
  ```
یادداشت: استرایپ معمولاً کارت خام را در تست رد می‌کند؛ برای OK سریع از `pm_card_visa` با `--pm` استفاده کنید.

---

## 🖥️ GUI (English)
Run GUI:
```bash
python card_checker_gui.py
```
- Choose file or Manual input
- pm mode for `pm_...`
- Generate by BIN → fills manual input with Luhn‑valid cards
- Predict (no transactions) / Live mode (`sk_live_...`)
- Stop / Clear buttons

## 🖥️ GUI (فارسی)
اجرا:
```bash
python card_checker_gui.py
```
- انتخاب فایل یا ورودی دستی
- حالت pm برای `pm_...`
- Generate by BIN → ساخت کارت‌های لوهِن و پرکردن ورودی دستی
- Predict (بدون تراکنش) / Live mode (با `sk_live_...`)
- دکمه‌های Stop و Clear

---

## 🧠 Prediction Rules | قوانین پیش‌بینی
`predict_rules.json` شامل کلیدواژه‌ها و وزن‌هاست. خروجی‌ها:
- `prediction_score` (۰ تا ۱۰۰)
- `prediction_status`: Likely / Possibly / Unlikely Active

---

## 🔒 Security | امنیت
- هیچ کلیدی در کد هاردکد نشده؛ از `STRIPE_API_KEY` استفاده کنید.
- شماره کارت کامل ذخیره نمی‌شود (ماسک می‌شود).
- برای حالت لایو، الزامات PCI‑DSS را رعایت کنید.

---

## 🧰 Tech | تکنولوژی
- Python 3.10+
- Libraries: `stripe`, `requests`
- Files: `card_checker.py`, `card_checker_gui.py`, `predict_rules.json`

---

## 🙌 Contact | ارتباط
- Instagram: [rasoul.ranjbar84](https://instagram.com/rasoul.ranjbar84)
- Telegram: [@rasoulranjbar007](https://t.me/rasoulranjbar007)
- LinkedIn: [rasoul-ranjbar](https://www.linkedin.com/in/rasoul-ranjbar)

---

## 📄 License
MIT
