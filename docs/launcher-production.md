# Launcher ile HTTPS production

`python launcher.py prod`, arayüzü ve Django API'sini tek HTTPS adresinde sunar.
Windows üzerinde AW Center benzeri doğrudan çalıştırma için hazırlanmıştır;
aynı komut macOS/Linux üzerinde de kullanılabilir. Python 3.11+ gerekir.
Node.js/npm yalnız bağımlılık kurulumu ve frontend derlemesi için gerekir.

## İki ayrı production profili

| Özellik | Launcher: `config.settings.native` | Mevcut: `config.settings.production` |
| --- | --- | --- |
| Sunucu | Uvicorn, doğrudan TLS | Docker/Gunicorn/Nginx |
| Veri | Repository dışında SQLite | PostgreSQL |
| Cache | Tek süreçte bellek | Redis |
| Frontend | Derlenmiş Vue + WhiteNoise | Mevcut frontend container'ı |
| Bağımlılıklar | `requirements/native.txt` | `requirements/production.txt` |

Mevcut Docker, PostgreSQL, Redis ve Celery dosyaları korunur; `prod` bunları
başlatmaz veya değiştirmez. Veriler otomatik taşınmaz. Native profil ayrı, boş bir
veritabanıyla başlar. Mevcut production verisini kullanmak için ayrıca doğrulanmış
veri taşıma çalışması gerekir.

SQLite profilinde Django view'ları bir kilit altında sırayla işlenir; böylece farklı
formatlar ve endpoint'ler aynı anda SQLite yazma transaction'ı açmaz. İşletim
sistemi dosya kilidi, aynı veri dizinini ikinci bir launcher'ın açmasını engeller.
Bu profil tek sunucu ve sınırlı yük içindir. Aynı veritabanıyla başka worker/server
çalıştırmayın. Yoğun trafik ve çoklu worker için korunan PostgreSQL/Redis profili
kullanılmalıdır. Bellekteki rate limit sayaçları yeniden başlatmada sıfırlanır.
Projede şu an uygulama Celery task'ı yoktur; native profil ileride eklenen task'ları
senkron yürütür ve hatalarını yayar; arka plan kuyruğu sağladığı varsayılmamalıdır.

## İlk kurulum

Repository kökünde:

```powershell
python launcher.py setup --environment production
```

[production.env.example](production.env.example) dosyasını repository dışındaki
bir dizine kopyalayın. `SECRET_KEY` alanını en az 50 karakter uzunluğunda,
kriptografik rastgele bir değerle doldurun; `NUMARATOR_DATA_DIR` için mutlak,
repository dışında ve yalnız uygulama hesabının yazabildiği yerel bir dizin seçin.
Env dosyasında `%LOCALAPPDATA%` veya `$HOME` gibi ifadeler genişletilmez; gerçek
mutlak yolu kullanın. SQLite, loglar ve toplanmış static dosyalar burada tutulur.
Env, anahtar ve veri dizini erişimini Windows ACL/POSIX izinleriyle sınırlandırın.
`backend/.env` bu profilde okunmaz. Shell'deki aynı isimli değişkenler env dosyasına
üstün gelir. DB/Redis ayarları native veri katmanını değiştirmez.

TLS sertifikası ve özel anahtarı da repository dışında saklayın. PEM formatında,
şifresiz özel anahtar ile eşleşen ve seçilen `--host` IPv4 adresini **IP SAN**
alanında içeren bir sertifika gerekir. Sertifika geçerli olmalı ve son kullanma
tarihine en az bir gün kalmalıdır. Sertifika zincirini istemciler güvenilir
bulmalıdır; launcher istemci trust store'una sertifika yüklemez. LAN'da sabit IP
kullanın. `127.0.0.1` yalnız yerel deneme içindir; `0.0.0.0` kabul edilmez.

```powershell
python launcher.py prod `
  --env-file "$env:LOCALAPPDATA\Numarator\production.env" `
  --host 192.0.2.10 `
  --tls-cert-file "$env:LOCALAPPDATA\Numarator\server.crt" `
  --tls-key-file "$env:LOCALAPPDATA\Numarator\server.key" `
  --build-frontend --migrate
```

Örnekteki IP'yi sunucunun gerçek IP adresiyle değiştirin. Varsayılan port 443'tür;
gerekirse `--port 8443` kullanın. Seçilen portun işletim sistemi izinleri ve
güvenlik duvarı kuralları uygulama hesabına erişim sağlamalıdır.

`--build-frontend` mevcut npm bağımlılıklarıyla build yapar; paket kurmaz.
Build sırasında API `/api/v1`, CSRF çerezi `csrftoken` olarak sabitlenir; production
secret'ları npm sürecine aktarılmaz. Build manifesti sayesinde eksik/değiştirilmiş
artifact ile açılış reddedilir. Elle `npm run build` sonrasında da native build'i
`--build-frontend` ile yeniden üretin.

`--migrate` yalnız ilk kurulumda veya kontrollü release geçişinde verilir.
Normal açılışta verilmez; bekleyen migration varsa servis başlamaz. Sertifika,
deploy check, migration drift ve frontend doğrulaması migration'dan önce yapılır.
Başarılı kontrollerden sonra static dosyalar toplanır ve HTTPS açılır. Arayüz,
API, admin ve static aynı origin'i kullanır. Kullanıcı yüklemeleri `/media/`
üzerinden herkese açık sunulmaz.

## Normal başlatma ve kontrol

Sonraki açılışlarda aynı komutu `--migrate` ve `--build-frontend` olmadan çalıştırın.
Terminal açık kalır; Ctrl+C servis ağacını durdurur. Otomatik Windows servisi veya
logon görevi oluşturulmaz. HTTP listener yoktur; bağlantıyı `https://` ile yapın.

Sunucuyu açmadan doğrulamak için aynı komuta `--check` ekleyin. Bu seçenek migration
uygulamaz, build veya collectstatic çalıştırmaz; log/kilit dosyaları oluşturabilir.
`--check`, `--migrate` veya `--build-frontend` ile birlikte kullanılamaz.

### Başlangıçta `No changes detected` ardından kapanma

`No changes detected`, modeller için yeni migration dosyası gerekmediğini söyler;
veritabanındaki migration'ların uygulanmış olduğunu göstermez. Eski launcher
sürümlerinde bekleyen migration varsa Django açıklama yazmadan `code 1` ile
kapanır. Güncel sürüm `Unapplied database migrations` mesajını gösterir.

İlk kurulumda veya kontrollü güncellemede, mevcut veri varsa servis kapalıyken
`NUMARATOR_DATA_DIR` yedeğini alın; aynı `prod` komutunu `--migrate` ekleyerek
çalıştırın. Env dosyası ve veri dizini aynı kalmalıdır. Frontend elle
`npm run build` ile üretildiyse ayrıca `--build-frontend` ekleyin. Sonraki normal
açılışlarda bu iki seçeneği kaldırın.

İlk yönetici hesabını oluşturmak için sunucuyu durdurup aynı native profil ile:

```powershell
$env:DJANGO_SETTINGS_MODULE = 'config.settings.native'
$env:NUMARATOR_ENV_FILE = "$env:LOCALAPPDATA\Numarator\production.env"
$env:NUMARATOR_HOST = '192.0.2.10'
$env:NUMARATOR_PORT = '443'
& .\backend\.venv\Scripts\python.exe .\backend\manage.py createsuperuser
```

Launcher kendi alt süreçlerinde ayar profilini seçer; dev komutu yine development
profilini kullanır. Yönetim komutları, yedekleme ve restore sırasında launcher'ı
kapalı tutun. Servis durduktan sonra `NUMARATOR_DATA_DIR` ve env dosyasını güvenli
biçimde yedekleyin; migration öncesinde de yedek alın. Private key'i ayrı koruyun.

## Offline production

Hedefle aynı işletim sistemi, mimari ve Python minor sürümünde:

```powershell
python launcher.py prepare-offline --environment production
python launcher.py package-offline --environment production
```

Hedefte ZIP açıldıktan sonra:

```powershell
python launcher.py setup --mode offline --environment production
# Ardından yukarıdaki prod komutu: --build-frontend --migrate
```

Manifest ortamı, requirement içeriklerini, platformu ve artifact checksum'larını
kontrol eder. Development bundle'ı production kurulumu için kullanılamaz.
Frontend build hedefte yapıldığı için Node.js/npm hedefte de bulunmalıdır.
Env, TLS key/sertifika, veri dizini ve frontend build paketlenmez.

## Bağımlılık ve doğrulama

Uvicorn (BSD-3-Clause) TLS sunucusu; WhiteNoise (MIT) production static sunumu;
cryptography (Apache-2.0 veya BSD-3-Clause) SAN, geçerlilik ve anahtar eşleşmesi
kontrolleri için eklenmiştir. Django runserver production için uygun değildir;
mevcut Gunicorn Windows'ta native çalışmaz. Standart SSL kütüphanesi sunucu
sertifikası için gereken X.509 inceleme API'sini sağlamaz. Uvicorn'un minimal
paketi kullanılır; cryptography platform wheel'i ve CFFI kurulum boyutunu artırır.
Sürümler `native.txt` içinde sabittir; Python/Django bağımlılık güncellemeleri ayrı
bir bakım çalışmasıdır.

```powershell
python -m unittest scripts.test_launcher
& .\backend\.venv\Scripts\python.exe -m unittest scripts.test_native
```

Native testler geçici env, sertifika ve veritabanıyla gerçek localhost HTTPS,
SPA/static/API, sertifika hataları, veri kilidi ve migration davranışını kontrol
eder. Production sertifikası veya mevcut veritabanı kullanılmaz.
