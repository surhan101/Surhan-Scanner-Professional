Surhan Scanner Agent Enterprise

حزمة التثبيت المعتمدة حاليًا:

SurhanScannerAgentSetup-1.0.1.exe

نوع الحزمة:

مثبت Windows Service

وضع التشغيل:

windows_service

اسم الخدمة:

SurhanScannerAgent

اسم العرض في Windows Services:

Surhan Scanner Agent

طريقة التثبيت:

1. قم بتنزيل ملف SurhanScannerAgentSetup-1.0.1.exe.
2. شغل الملف كمسؤول Administrator.
3. وافق على نافذة الصلاحيات UAC إذا ظهرت.
4. سيقوم المثبت بتثبيت البرنامج داخل:
   C:\Program Files\SurhanScannerAgent
5. سيقوم المثبت بإنشاء خدمة Windows باسم:
   SurhanScannerAgent
6. سيتم تشغيل الخدمة تلقائيًا.
7. بعد إعادة تشغيل الجهاز، ستعمل الخدمة تلقائيًا لأنها مضبوطة على Automatic.

طريقة التحقق بعد التثبيت:

افتح PowerShell كمسؤول ونفذ:

Get-Service SurhanScannerAgent

المطلوب أن تكون الحالة:

Running

للتحقق من إعداد الخدمة:

Get-CimInstance Win32_Service -Filter "Name='SurhanScannerAgent'" |
Select-Object Name, DisplayName, State, StartMode, StartName, PathName

المطلوب:

State = Running
StartMode = Auto
StartName = LocalSystem

للتحقق من عمل الـ Agent:

Invoke-WebRequest http://127.0.0.1:8787/health -UseBasicParsing

المطلوب:

StatusCode = 200

للتحقق من أجهزة السكانر:

Invoke-WebRequest http://127.0.0.1:8787/devices -UseBasicParsing

إذا لم يكن هناك Scanner متصل، فمن الطبيعي أن تظهر الرسالة:

No scanners found

ملاحظات مهمة:

- التثبيت يتطلب صلاحية Administrator.
- الخدمة تعمل تلقائيًا بعد إعادة تشغيل Windows.
- الخدمة تعمل من المسار:
  C:\Program Files\SurhanScannerAgent\SurhanScannerAgent.exe
- ملف الإعداد يمكن أن يوجد في:
  C:\SurhanScannerAgent\surhan_agent_config.json
  أو:
  C:\ProgramData\SurhanScannerAgent\surhan_agent_config.json
- يجب كتابة ملف الإعداد بصيغة UTF-8 بدون BOM إذا تم تعديله يدويًا.
- إذا كان المستخدم يدخل فارابي من متصفح، يجب أن يكون رابط فارابي موجودًا ضمن allowed_farabi_origins.
- حاليًا الروابط المعتمدة في البيئة المختبرة:
  https://farabi.example.com
  http://FARABI-SERVER-IP

تنبيه:

الحزم ZIP السابقة موجودة للرجوع فقط، وليست حزمة التنزيل الإنتاجية الحالية بعد اعتماد Windows Service Installer.


ملاحظة قابلية النقل:
لا تعتمد نسخة GitHub على IP ثابت. عند تثبيت Agent على جهاز مستخدم جديد، يجب ضبط رابط فارابي الفعلي داخل ملف إعدادات Agent باستخدام سكربت:
Configure-SurhanScannerAgent.ps1

أمثلة لرابط فارابي:
https://farabi.example.com
http://FARABI-SERVER-IP
