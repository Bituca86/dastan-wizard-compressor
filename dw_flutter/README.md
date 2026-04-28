# ◈ DASTAN WIZARD — Video Compressor Android
## Flutter + ffmpeg_kit_flutter · v1.0

Calitate **identică** cu versiunea Desktop EXE — același FFmpeg, aceiași parametri.

---

## 📦 Ce include
- H.264 / H.265 / VP9 cu CRF slider (16–40)
- 8 speed presets (ultrafast → slower)
- SSIM quality analysis
- Web-stream faststart
- Batch processing cu progress live (fps, speed, %)
- Share/export fișiere comprimate

---

## 🔨 BUILD APK — Metoda 1: Local

### Cerințe
- **Flutter SDK** → https://docs.flutter.dev/get-started/install/windows/mobile
- **Android SDK** (vine cu Android Studio sau Flutter)
- Java 17+

### Pași
```bash
# 1. Navighează în folderul proiectului
cd dastan_wizard_android

# 2. Instalează dependențele
flutter pub get

# 3. Build APK release
flutter build apk --release --target-platform android-arm64

# APK-ul se găsește la:
# build/app/outputs/flutter-apk/app-release.apk
```

### Instalare APK pe telefon
```bash
# Via ADB (cablu USB)
adb install build/app/outputs/flutter-apk/app-release.apk

# SAU: transferă APK-ul pe telefon și deschide-l
# (trebuie activat "Install from unknown sources" în Settings)
```

---

## ☁️ BUILD APK — Metoda 2: Codemagic (cloud, GRATUIT)

Fără instalare locală — se compilează în cloud.

1. Mergi la **https://codemagic.io** → Sign up (gratuit)
2. **Add application** → selectează **Flutter App**
3. Conectează GitHub sau upload ZIP cu proiectul
4. Click **Start new build** → alege **Android APK**
5. Descarcă APK-ul din artefacte

**Atenție**: Prima build durează ~15–20 minute.

---

## ☁️ BUILD APK — Metoda 3: GitHub Actions (gratuit)

1. Creează un repo GitHub și push proiectul
2. Creează `.github/workflows/build.yml`:

```yaml
name: Build APK
on: [push]
jobs:
  build:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v3
      - uses: subosito/flutter-action@v2
        with:
          flutter-version: '3.19.0'
      - run: flutter pub get
      - run: flutter build apk --release --target-platform android-arm64
      - uses: actions/upload-artifact@v3
        with:
          name: DastanWizard-APK
          path: build/app/outputs/flutter-apk/app-release.apk
```

3. Push → Actions → descarcă APK din artefacte

---

## 📱 Cerințe telefon
- Android 7.0+ (API 24)
- ARM64 (toate telefoanele moderne)
- ~50 MB spațiu (include FFmpeg compiled)

---

## 🐛 Troubleshoot

**Eroare gradle**: Asigură-te că ai Java 17 instalat
```
export JAVA_HOME=/path/to/java17
```

**Eroare permissions**: Permite acces la fișiere în Settings → Apps → Dastan Wizard → Permissions

**APK prea mare**: Normal, ~45-55 MB datorită FFmpeg compiled pentru ARM64
