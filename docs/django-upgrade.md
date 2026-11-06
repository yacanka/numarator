# Django 5.2 LTS yükseltmesi

Backend Django **5.2.19** ve Django REST Framework **3.16.1** kullanır.
Projenin mevcut **Python 3.11+** gereksinimi değişmez. Yeni runtime bağımlılığı
eklenmedi; diğer doğrudan bağımlılıkların sürümleri korundu.

Django 4.2 desteği 7 Nisan 2026'da sona erdi. Django 5.2 LTS'nin güvenlik
desteği Nisan 2028'e kadar sürer. DRF 3.16 serisi Django 5.2 desteği sağlar.
Kaynaklar: [Django destek tablosu](https://www.djangoproject.com/download/),
[DRF 3.16 duyurusu](https://www.django-rest-framework.org/community/3.16-announcement/).

## Kurulum ve mevcut veriler

Geliştirme ortamında `python launcher.py setup --skip-frontend`, native
production ortamında `python launcher.py setup --environment production
--skip-frontend` ile uygun requirements dosyasını kurun. Production kurulumu
için mevcut [native HTTPS rehberindeki](launcher-production.md) veya
[Docker rehberindeki](docker-production.md) çalışma yöntemini izleyin.

Bu değişiklik uygulama modeli veya migration dosyası değiştirmez. Kurulumdan
önce veritabanını yedekleyin; framework/bağımlılık migration durumunu kullanılan
profilde `migrate --plan` ile gözden geçirin. Gerçek veritabanına migration
uygulamak normal deployment adımınız olarak kalır; inceleme testleri yalnızca
geçici veritabanlarını kullanır.

Mevcut cookie adları, API URL'leri ve yanıt zarfları korunur. Kayıtlı parolalar
Django'nun standart doğrulama/yükseltme mekanizmasıyla çalışmaya devam eder;
hesap veya oturum verisi temizlenmez.

## Offline dağıtım

Requirements değiştiği için eski offline manifest/cache yeni sürüm için
kullanılamaz. Hedefle aynı işletim sistemi, mimari ve Python minor sürümünde
`prepare-offline` ve `package-offline` komutlarını yeniden çalıştırın; native
paketlerde mevcut `--environment production` seçeneğini koruyun.

## Doğrulama

Yükseltme önce ayrı bir geçici sanal ortamda doğrulandı. Regresyon kapsamı;
cookie/CSRF giriş-yenileme, özel API yetkileri/idempotency, belge üretimi,
OpenAPI şeması ve native HTTPS runtime testlerini içerir. Django sistem
kontrolü, migration dry-run ve paket bağımlılık tutarlılığı ayrıca kontrol
edilir. Dağıtımda `python launcher.py check` ve `python launcher.py test`
komutlarını kullanın.
