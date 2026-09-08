# Numarator

Numarator, tanımlı formatlardan atomik ve izlenebilir belge numaraları üreten Django REST + Vue uygulamasıdır.

- Tarayıcı arayüzü API'si: `/api/v1/`
- Dış uygulamalar için özel API: `/api/private/v1/`
- OpenAPI şeması: `/api/schema/`
- Swagger arayüzü: `/api/docs/`

Dış uygulama entegrasyonunun kimlik doğrulama, endpoint, idempotency, hata ve güvenlik ayrıntıları için [Özel API entegrasyon rehberine](docs/private-api.md) bakın.

## Yerel geliştirme

Proje kök dizinindeki Numarator'a özel launcher bağımlılık kurulumunu, kontrolleri,
testleri, geliştirme servislerini ve offline paketlemeyi yönetir:

```bash
python launcher.py setup
python launcher.py check
python launcher.py test
python launcher.py dev --migrate
```

`dev` komutunda migration yalnızca `--migrate` açıkça verildiğinde uygulanır.
Backend `http://127.0.0.1:8000`, frontend `http://127.0.0.1:5173` üzerinde açılır.

AW Center gibi ikinci bir Django/Vue uygulamasıyla aynı anda çalıştırmak için:

```bash
python launcher.py dev --backend-port 8100 --frontend-port 5174 --migrate
```

Bu durumda Numarator backend `http://127.0.0.1:8100`, arayüz
`http://127.0.0.1:5174` üzerinde çalışır. Launcher Vite proxy'sini ve development
CSRF/CORS origin'lerini seçilen portlarla eşler; dolu veya aynı portlarla
başlatmayı reddeder. Development cookie'leri `dn_csrftoken` ve `dn_sessionid`
adlarını kullanır, böylece aynı hosttaki diğer uygulamanın oturumunu etkilemez.

Eski geliştirme kısayolları da kullanılabilir. macOS/Linux üzerinde:

```bash
./start-dev.sh
```

Windows üzerinde:

```bat
start-dev.bat
```

Başlatıcı backend bağımlılıklarını ve frontend paketlerini kurar, Django kontrollerini/migration'ları çalıştırır ve iki servisi başlatır.

## Offline kurulum

Offline bağımlılıkları internet erişimi olan ve hedef bilgisayarla aynı işletim sistemi,
mimari ve Python minor sürümüne sahip bir bilgisayarda hazırla:

```bash
python launcher.py prepare-offline
python launcher.py package-offline
```

Üretilen `numarator-offline.zip` hedef bilgisayarda açıldıktan sonra:

```bash
python launcher.py setup --mode offline
python launcher.py dev --migrate
```

Yalnız frontend bağımlılıkları hazırlanacak/kurulacaksa her iki tarafta da aynı scope
kullanılmalıdır. Kaynak kodun tamamı ZIP'te kalır:

```bash
python launcher.py prepare-offline --skip-backend
python launcher.py package-offline --skip-backend
python launcher.py setup --mode offline --skip-backend
```

`prepare-offline`, npm cache'ini geçici ve temiz bir kurulum dizininde doldurur ve ikinci
bir tamamen offline `npm ci` ile doğrular. Böylece eksik cache paketleri ZIP oluşturulmadan
önce tespit edilir. `node_modules`, sanal ortam, veritabanı, log ve `.env` dosyaları pakete
alınmaz.
