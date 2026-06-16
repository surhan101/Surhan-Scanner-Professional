# Phase 06 Agent Version Decision

## النتيجة

آخر نسخة Runtime موجودة فعليًا هي:

Surhan Scanner Agent Enterprise v1.0.2

## سبب الاعتماد

الملفات الموجودة داخل releases هي:

- SurhanScannerAgent-v1.0.0.zip
- SurhanScannerAgent-v1.0.1.zip
- SurhanScannerAgent-v1.0.2.zip
- SurhanScannerAgentSetup-1.0.0.exe

وبحسب رقم النسخة فإن 1.0.2 هي أحدث Runtime.

## ملاحظة مهمة عن الخدمة

الحزمة SurhanScannerAgent-v1.0.2.zip لا تحتوي على مثبت Windows Service.

محتواها الأساسي:

- SurhanScannerAgent.exe
- surhan_agent_config.json
- update_manifest.json
- version.json

كما أن config يشير إلى:

deployment_mode = user_startup_watchdog

لذلك سيتم اعتماد 1.0.2 كآخر Runtime، وليس كـ Windows Service installer.

## القرار

- latest_version = 1.0.2
- package = SurhanScannerAgent-v1.0.2.zip
- package_type = runtime_zip
- deployment_mode = user_startup_watchdog
- windows_service_installer = false
- minimum_supported_version = 1.0.0
- بناء Setup 1.0.2 أو Service Installer سيكون مرحلة مستقلة لاحقًا.
