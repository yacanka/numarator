# Docker ile HTTPS production

Bu profil PostgreSQL, Redis, Gunicorn, Celery ve Nginx kullanır. Native launcher
profilinden bağımsızdır; mevcut native SQLite verisini otomatik taşımaz.

## Yapılandırma

Komutları repository kökünde çalıştırın. Yeni kurulumda `backend/.env.example`
dosyasını `backend/docker/.env` konumuna kopyalayın. Mevcut kurulumun env dosyasını
değiştirmeden önce yedekleyin; mevcut `DB_NAME` ve `DB_USER` değerlerini koruyun.

`SECRET_KEY` için en az 50 karakterlik kriptografik rastgele değer, `DB_PASSWORD`
için güçlü bir parola ve `ALLOWED_HOSTS` için gerçek DNS adı veya IP adresini
tanımlayın. `ALLOWED_HOSTS` içine protokol veya port eklemeyin. Varsayılan container
bağlantıları `DB_HOST=db`, `DB_PORT=5432`, `REDIS_URL=redis://redis:6379/0` kullanır.

Nginx'in TLS dosyalarını şu yollarla sağlayın:

- `backend/docker/ssl/server.crt`: sunucu sertifikası ve gerekiyorsa ara
  sertifikaların PEM zinciri.
- `backend/docker/ssl/server.key`: sertifikayla eşleşen şifresiz PEM private key.

Sertifika gerçek DNS adını/IP adresini kapsamalı ve istemciler tarafından güvenilir
olmalıdır. Env dosyasına ve private key'e erişimi yalnız uygulama yöneticisiyle
sınırlandırın. `ssl/` Git dışında tutulur; secret dosyaları, yerel veritabanları ve
loglar `.dockerignore` allowlist'leriyle build context dışında kalır. İmajlar yalnız
uygulama kaynaklarını içerir; env ve TLS dosyaları runtime'da sağlanır. Frontend
build'i aynı origin'deki `/api/v1` adresini kullanır; yerel `.env` ve `.npmrc`
dosyaları build'e aktarılmaz.

## Başlatma

Önce production verisinin yedeğini alın. Mevcut davranış korunarak backend açılışta
migration ve `collectstatic` çalıştırır; bunlardan biri başarısız olursa Gunicorn
başlatılmaz. Migration içeren güncellemeleri kontrollü bakım aralığında uygulayın.

```bash
docker compose --env-file backend/docker/.env -f backend/docker/docker-compose.yml up -d --build
```

Arayüz, API ve admin `https://SUNUCU/` üzerinden sunulur. Port 80 yalnız HTTPS'e
yönlendirir; 443 TLS dinler. Yalnız Nginx host portlarını yayımlar. **Gunicorn'un
8000 portunu host'a yayımlamayın:** Django, özel container ağı üzerindeki Nginx'in
üzerine yazdığı `X-Forwarded-Proto` başlığına güvenir. Bu ağdaki container'ları
güvenilen uygulama bileşenleriyle sınırlayın. Harici bir proxy eklenecekse TLS ve
güvenilen proxy zincirini ayrıca yapılandırın.

SPA sayfalarının yenilenmesi frontend container'ındaki Nginx tarafından
`index.html` dosyasına yönlendirilir; bulunamayan `/assets/` dosyaları 404 döner.
Static/media ve veritabanı volume'ları mevcut isimlerini korur.

## Regresyon kontrolü

Python test bağımlılıkları kurulduktan sonra:

```bash
docker pull nginx:1.27-alpine
docker pull node:22-bookworm-slim
backend/.venv/bin/python -m unittest scripts.test_deployment
```

Windows'ta Python yolu `backend\.venv\Scripts\python.exe` olur. Docker daemon'ına
erişim gerekir. Testler sentetik secret dosyalarının build context dışında
kaldığını, shell başlangıcını, Django HTTPS algısını ve geçici sertifikalı gerçek
Nginx TLS/SPA/API/admin akışını doğrular. Üretim env/TLS dosyalarını veya verilerini
kullanmazlar; yalnız kendi adlandırılmış geçici container, ağ ve imajlarını kaldırırlar.
Docker erişimi veya test imajları yoksa ilgili kontroller açıkça skipped raporlanır.
