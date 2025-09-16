# Card Checker

[فارسی](#فارسی) | [English](#english)

---

## فارسی

یک ابزار جامع برای تست و بررسی کارت‌های اعتباری با استفاده از Stripe API و BIN lookup

## ویژگی‌ها

### 🔧 ابزارهای اصلی
- **تست کارت‌ها**: بررسی کارت‌ها با Stripe (test mode)
- **BIN Lookup**: دریافت اطلاعات بانک، نوع کارت و کشور
- **تولید کارت**: ساخت کارت‌های Luhn-valid برای تست
- **پیش‌بینی فعالیت**: تحلیل احتمال فعال بودن کارت بدون تراکنش

### 🎯 رابط‌های کاربری
1. **GUI (Tkinter)**: رابط گرافیکی کامل و کاربرپسند
2. **CLI**: ابزار خط فرمان برای استفاده خودکار

### 📁 فرمت‌های پشتیبانی‌شده
- **TXT**: `number|month|year|cvv` در هر خط
- **CSV**: ستون‌های `number,month,year,cvv`
- **JSON**: آرایه از آبجکت‌ها با فیلدهای مورد نیاز
- **JSON nested**: پشتیبانی از ساختار `{"CreditCard": {...}}`
- **Payment Methods**: pm_card_* tokens برای Stripe

## نصب و راه‌اندازی

### پیش‌نیازها
```bash
pip install requests stripe
```

### متغیرهای محیطی
```bash
export STRIPE_API_KEY="sk_test_your_key_here"
```

## استفاده

### رابط گرافیکی (GUI)
```bash
python card_checker_gui.py
```

#### امکانات GUI:
- **بارگذاری فایل**: انتخاب فایل‌های TXT/CSV/JSON
- **ورودی دستی**: تایپ مستقیم کارت‌ها
- **تولیدکننده‌ها**:
  - تولید بر اساس BIN
  - تولید تصادفی با نام
  - تولید token های تست (pm_card_*)
- **حالت‌های مختلف**:
  - تست عادی
  - پیش‌بینی (بدون تراکنش)
  - حالت زنده (live mode)
- **نمایش نتایج**: جدول تعاملی با امکان export

### خط فرمان (CLI)

#### تست فایل ورودی:
```bash
python card_checker.py -i cards.txt
```

#### تولید کارت‌های تست:
```bash
python card_checker.py --generate-bin 424242 20
```

#### حالت پیش‌بینی:
```bash
python card_checker.py --predict -i cards.txt
```

#### حالت زنده (نیاز به sk_live_):
```bash
python card_checker.py --live-mode -i cards.txt
```

## فرمت‌های ورودی

### فایل TXT
```
4242424242424242|12|2026|123
5555555555554444|12|2026|123
```

### فایل CSV
```csv
number,month,year,cvv
4242424242424242,12,2026,123
5555555555554444,12,2026,123
```

### فایل JSON
```json
[
  {
    "number": "4242424242424242",
    "month": "12",
    "year": "2026",
    "cvv": "123"
  }
]
```

### JSON Nested (CreditCard)
```json
[
  {
    "CreditCard": {
      "CardNumber": "4242424242424242",
      "Exp": "12/2026",
      "CVV": "123"
    }
  }
]
```

## تولید کارت‌های تست

### بر اساس BIN مشخص:
```bash
python card_checker.py --generate-bin 424242 50
```

### تولید تصادفی با نام:
```bash
python card_checker.py --generate-random 20
```

### با BIN اختیاری:
```bash
python card_checker.py --generate-random 20 555555
```

## سیستم پیش‌بینی

سیستم پیش‌بینی بر اساس BIN lookup و قوانین موجود در `predict_rules.json` عمل می‌کند:

### معیارهای امتیازدهی:
- **کلمات e-commerce**: +50 امتیاز
- **بانک‌های آنلاین شناخته‌شده**: +30 امتیاز
- **کلمات POS-only**: -80 امتیاز
- **بانک‌های POS-only**: -90 امتیاز

### نتایج پیش‌بینی:
- **70+ امتیاز**: احتمالاً فعال
- **40-69 امتیاز**: ممکن است فعال
- **زیر 40**: احتمالاً غیرفعال

## پارامترهای خط فرمان

```bash
# ورودی
-i, --input          مسیر فایل ورودی
-c, --currency       واحد پول (پیش‌فرض: usd)
--retries           تعداد تلاش مجدد (پیش‌فرض: 2)

# حالت‌ها
--predict           حالت پیش‌بینی (بدون تراکنش)
--live-mode         حالت زنده ($0.50 auth)
--pm                ورودی را payment_method id در نظر بگیر

# تولید
--generate-bin BIN COUNT         تولید کارت از BIN
--generate-random [COUNT] [BIN]  تولید تصادفی

# امنیت
--insecure          غیرفعال کردن SSL verification
```

## فایل‌های خروجی

همه نتایج در دو فرمت ذخیره می‌شوند:
- `results.csv`
- `results.json`

### ساختار خروجی:
```json
{
  "masked_number": "424242XXXXXX4242",
  "month": "12",
  "year": "2026",
  "status": "Live/Test OK",
  "message": null,
  "bin_bank": "Sample Bank",
  "bin_scheme": "visa",
  "bin_type": "debit",
  "bin_brand": "Visa",
  "bin_country": "US"
}
```

## کارت‌های تست Stripe

### معتبر:
- **Visa**: 4242424242424242
- **Mastercard**: 5555555555554444
- **American Express**: 378282246310005
- **Discover**: 6011111111111117

### رد شده:
- **Generic decline**: 4000000000000002
- **Insufficient funds**: 4000000000009995
- **Lost card**: 4000000000009987

## امنیت و محدودیت‌ها

### ⚠️ هشدارهای امنیتی:
- همیشه از test keys استفاده کنید
- کارت‌های واقعی را در فایل ذخیره نکنید
- فایل‌های حاوی کارت را secure نگه دارید

### محدودیت‌ها:
- BIN lookup محدود به 6 رقم اول
- Stripe rate limits اعمال می‌شود
- Live mode نیاز به مجوز ویژه دارد

## عیب‌یابی

### خطاهای رایج:

#### 1. Stripe API Key نامعتبر:
```
Error: Environment variable STRIPE_API_KEY is not set.
```
**حل**: کلید API را در متغیر محیطی تنظیم کنید

#### 2. خطای SSL:
```
SSL verification failed
```
**حل**: از پارامتر `--insecure` استفاده کنید (فقط در شبکه‌های محدود)

#### 3. خطای فرمت فایل:
```
Unsupported file extension
```
**حل**: از فرمت‌های .txt، .csv یا .json استفاده کنید

## مثال‌های کاربردی

### 1. تست سریع:
```bash
echo "4242424242424242|12|2026|123" | python card_checker.py
```

### 2. تولید و تست خودکار:
```bash
python card_checker.py --generate-bin 424242 10 && python card_checker.py -i generated_cards.txt
```

### 3. پیش‌بینی bulk:
```bash
python card_checker.py --predict -i large_cardlist.csv
```

## توسعه و مشارکت

### ساختار پروژه:
```
CHECK CARD/
├── card_checker.py      # ماژول اصلی CLI
├── card_checker_gui.py  # رابط گرافیکی
├── predict_rules.json   # قوانین پیش‌بینی
└── README.md           # مستندات
```

### الگوریتم Luhn:
تمام کارت‌های تولیدی از الگوریتم Luhn برای اعتبارسنجی استفاده می‌کنند.

## لایسنس

این پروژه تحت لایسنس MIT منتشر شده است.

## پشتیبانی

برای گزارش باگ یا درخواست ویژگی جدید، issue جدید ایجاد کنید.

---

**نکته**: این ابزار فقط برای اهداف تست و توسعه طراحی شده است. استفاده از آن برای اهداف غیرقانونی ممنوع است.

---

## English

A comprehensive tool for testing and validating credit cards using Stripe API and BIN lookup services.

## Features

### 🔧 Core Tools
- **Card Testing**: Validate cards with Stripe (test mode)
- **BIN Lookup**: Retrieve bank, card type, and country information
- **Card Generation**: Create Luhn-valid test cards
- **Activity Prediction**: Analyze card activity likelihood without transactions

### 🎯 User Interfaces
1. **GUI (Tkinter)**: Complete and user-friendly graphical interface
2. **CLI**: Command-line tool for automated usage

### 📁 Supported Formats
- **TXT**: `number|month|year|cvv` per line
- **CSV**: `number,month,year,cvv` columns
- **JSON**: Array of objects with required fields
- **JSON nested**: Support for `{"CreditCard": {...}}` structure
- **Payment Methods**: pm_card_* tokens for Stripe

## Installation & Setup

### Prerequisites
```bash
pip install requests stripe
```

### Environment Variables
```bash
export STRIPE_API_KEY="sk_test_your_key_here"
```

## Usage

### Graphical Interface (GUI)
```bash
python card_checker_gui.py
```

#### GUI Features:
- **File Loading**: Select TXT/CSV/JSON files
- **Manual Input**: Direct card entry
- **Generators**:
  - BIN-based generation
  - Random generation with names
  - Test token generation (pm_card_*)
- **Different Modes**:
  - Normal testing
  - Prediction (no transactions)
  - Live mode
- **Results Display**: Interactive table with export capability

### Command Line (CLI)

#### Test input file:
```bash
python card_checker.py -i cards.txt
```

#### Generate test cards:
```bash
python card_checker.py --generate-bin 424242 20
```

#### Prediction mode:
```bash
python card_checker.py --predict -i cards.txt
```

#### Live mode (requires sk_live_):
```bash
python card_checker.py --live-mode -i cards.txt
```

## Input Formats

### TXT File
```
4242424242424242|12|2026|123
5555555555554444|12|2026|123
```

### CSV File
```csv
number,month,year,cvv
4242424242424242,12,2026,123
5555555555554444,12,2026,123
```

### JSON File
```json
[
  {
    "number": "4242424242424242",
    "month": "12",
    "year": "2026",
    "cvv": "123"
  }
]
```

### JSON Nested (CreditCard)
```json
[
  {
    "CreditCard": {
      "CardNumber": "4242424242424242",
      "Exp": "12/2026",
      "CVV": "123"
    }
  }
]
```

## Test Card Generation

### Based on specific BIN:
```bash
python card_checker.py --generate-bin 424242 50
```

### Random generation with names:
```bash
python card_checker.py --generate-random 20
```

### With optional BIN:
```bash
python card_checker.py --generate-random 20 555555
```

## Prediction System

The prediction system works based on BIN lookup and rules in `predict_rules.json`:

### Scoring Criteria:
- **E-commerce keywords**: +50 points
- **Known online banks**: +30 points
- **POS-only keywords**: -80 points
- **POS-only banks**: -90 points

### Prediction Results:
- **70+ points**: Likely Active
- **40-69 points**: Possibly Active
- **Below 40**: Unlikely Active

## Command Line Parameters

```bash
# Input
-i, --input          Input file path
-c, --currency       Currency (default: usd)
--retries           Retry count (default: 2)

# Modes
--predict           Prediction mode (no transactions)
--live-mode         Live mode ($0.50 auth)
--pm                Treat input as payment_method id

# Generation
--generate-bin BIN COUNT         Generate cards from BIN
--generate-random [COUNT] [BIN]  Random generation

# Security
--insecure          Disable SSL verification
```

## Output Files

All results are saved in two formats:
- `results.csv`
- `results.json`

### Output Structure:
```json
{
  "masked_number": "424242XXXXXX4242",
  "month": "12",
  "year": "2026",
  "status": "Live/Test OK",
  "message": null,
  "bin_bank": "Sample Bank",
  "bin_scheme": "visa",
  "bin_type": "debit",
  "bin_brand": "Visa",
  "bin_country": "US"
}
```

## Stripe Test Cards

### Valid:
- **Visa**: 4242424242424242
- **Mastercard**: 5555555555554444
- **American Express**: 378282246310005
- **Discover**: 6011111111111117

### Declined:
- **Generic decline**: 4000000000000002
- **Insufficient funds**: 4000000000009995
- **Lost card**: 4000000000009987

## Security & Limitations

### ⚠️ Security Warnings:
- Always use test keys
- Never store real cards in files
- Keep card-containing files secure

### Limitations:
- BIN lookup limited to first 6 digits
- Stripe rate limits apply
- Live mode requires special authorization

## Troubleshooting

### Common Errors:

#### 1. Invalid Stripe API Key:
```
Error: Environment variable STRIPE_API_KEY is not set.
```
**Solution**: Set the API key in environment variable

#### 2. SSL Error:
```
SSL verification failed
```
**Solution**: Use `--insecure` parameter (only in restricted networks)

#### 3. File Format Error:
```
Unsupported file extension
```
**Solution**: Use .txt, .csv, or .json formats

## Usage Examples

### 1. Quick test:
```bash
echo "4242424242424242|12|2026|123" | python card_checker.py
```

### 2. Generate and test automatically:
```bash
python card_checker.py --generate-bin 424242 10 && python card_checker.py -i generated_cards.txt
```

### 3. Bulk prediction:
```bash
python card_checker.py --predict -i large_cardlist.csv
```

## Development & Contribution

### Project Structure:
```
CHECK CARD/
├── card_checker.py      # Main CLI module
├── card_checker_gui.py  # Graphical interface
├── predict_rules.json   # Prediction rules
└── README.md           # Documentation
```

### Luhn Algorithm:
All generated cards use the Luhn algorithm for validation.

## License

This project is released under the MIT License.

## Support

For bug reports or feature requests, please create a new issue.

---

**Note**: This tool is designed only for testing and development purposes. Using it for illegal purposes is prohibited.