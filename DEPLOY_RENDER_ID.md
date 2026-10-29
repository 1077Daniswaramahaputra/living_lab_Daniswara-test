# Deployment ke Render — Dashboard Living Lab IoT

## File yang sudah disiapkan
- `requirements.txt`: dependensi Python termasuk Gunicorn.
- `Procfile`: perintah menjalankan Flask di hosting.
- `render.yaml`: konfigurasi service Render.
- `app.py`: mode debug dimatikan untuk deployment.

## Cara menerbitkan URL publik
1. Ekstrak ZIP ini ke folder di komputer.
2. Buat repository GitHub baru, misalnya `living-lab-iot-dashboard`.
3. Upload seluruh isi folder hasil ekstrak ke repository (jangan upload ZIP-nya sebagai satu file).
4. Buka https://render.com dan masuk/daftar.
5. Pilih **New +** → **Blueprint** (atau **Web Service** jika Blueprint tidak tersedia).
6. Hubungkan akun GitHub dan pilih repository tersebut.
7. Jika memakai Blueprint, Render membaca `render.yaml`. Jika memakai Web Service, pilih:
   - Runtime: Python
   - Build Command: `pip install -r requirements.txt`
   - Start Command: `gunicorn app:app --bind 0.0.0.0:$PORT --workers 1 --timeout 120`
8. Klik deploy dan tunggu status **Live**.
9. Buka URL `https://...onrender.com` yang diberikan Render dari HP dan PC.

## Google Sheets
Dashboard memakai CSV publik Google Sheets. Pastikan sheet dapat dibaca melalui link CSV tanpa login. Jika sheet privat, server tidak dapat mengambil datanya.
Di dashboard, gunakan fitur Google Sheets untuk memuat ulang sumber jika tersedia.

## Penting: penyimpanan dan privasi
- Paket hosting gratis biasanya memakai filesystem sementara. File yang diunggah atau perubahan `active_data.csv` bisa hilang setelah restart/redeploy. Untuk penggunaan berkelanjutan, gunakan sumber Google Sheets atau tambahkan database persisten.
- Jangan masukkan kata sandi Wi-Fi atau API key ESP32 ke repository publik.
- URL publik membuat dashboard dapat dibuka siapa pun yang memiliki URL. Jangan letakkan data rahasia di sheet publik.
- Saya sudah menyiapkan paket deployment, tetapi URL publik baru terbentuk setelah repository terhubung dan deployment dijalankan pada akun hosting milik Anda.
