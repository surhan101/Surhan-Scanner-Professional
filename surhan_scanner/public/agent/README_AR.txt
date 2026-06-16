Surhan Scanner Agent Enterprise v1.0.2

هذه حزمة نظيفة لتشغيل Surhan Scanner Agent على Windows x64.

محتويات الحزمة:
- SurhanScannerAgent.exe
- surhan_agent_config.json
- version.json
- install_user_startup.bat
- uninstall_user_startup.bat
- start_agent.bat
- README_AR.txt

طريقة التثبيت:
1. فك ضغط ملف SurhanScannerAgent-v1.0.2.zip
2. شغل install_user_startup.bat
3. سيتم إعداد Agent ليعمل مع بدء تشغيل المستخدم
4. لتشغيله يدويًا استخدم start_agent.bat
5. تحقق من التشغيل عبر:
   http://127.0.0.1:8787/health

طريقة الإزالة:
- شغل uninstall_user_startup.bat

أنواع الملفات المسموحة:
- PDF
- JPG / JPEG
- PNG
- TIF / TIFF

أنواع الملفات الممنوعة:
- TXT / CSV / RTF
- Word / Excel / PowerPoint
- EXE / BAT / CMD / PS1 / VBS / JS / HTML / SVG

ملاحظات:
- يجب أن يكون Scanner معرفًا على Windows.
- يستخدم Agent المنفذ 8787.
- إذا كان المنفذ مستخدمًا، أوقف النسخة القديمة:
  netstat -ano | findstr :8787
  taskkill /PID الرقم /F
- ملف SHA256SUMS.txt موجود خارج الحزمة للتحقق من سلامة الملفات والحزمة.

الإصدار:
- Agent Version: 1.0.2
- Package Type: ZIP
- Deployment Mode: User Startup

## ملاحظة التشغيل
هذه النسخة هي Runtime ZIP وتعمل بنمط user_startup_watchdog.
لا تحتوي هذه الحزمة على مثبت Windows Service مستقل.
ملف Setup الخاص بالخدمة يحتاج بناء نسخة مستقلة عند إصدار Service Installer.
