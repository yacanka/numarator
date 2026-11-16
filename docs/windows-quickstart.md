# Windows'ta çift tıklayarak başlatma

Proje kökündeki iki dosya, aynı Python launcher'ın hızlı başlangıç akışını açar:

| Dosya | Kullanım | Varsayılan adres |
| --- | --- | --- |
| `start-local.bat` | Yerel geliştirme | Arayüz: `http://127.0.0.1:5173`, API: `http://127.0.0.1:8000` |
| `start-prod.bat` | Native SQLite ile HTTPS production | İlk açılışta seçilen IPv4 adresi, port `443` |

Başlatıcı bulunduğu proje klasörünü kullanır; başka bir klasörden açılabilir.
Boşluk, Türkçe karakter veya `&`, `(`, `)`, `!` içeren klasör adlarında yollar
tırnak içinde aktarılır. Komut satırında kendi eklediğiniz dosya yollarını da
çift tırnak içine alın.

## Gereksinimler ve ilk açılış

- Python **3.11 veya üzeri**. Windows Python launcher'ı (`py`) veya PATH'te
  `python` bulunmalıdır. Başlatıcı önce `backend\.venv\Scripts\python.exe`,
  ardından `py -3`, `python` ve `python3` seçeneklerini sürüm kontrolüyle dener.
- Node.js **20 veya üzeri** ve npm. İlk bağımlılık kurulumu ve frontend derlemesi
  için gerekir.
- İlk kurulumda internet bağlantısı. Projeyi tüm dosyalarıyla bir klasöre çıkarın.

`start-local.bat` dosyasına çift tıklayın. Yeni kurulumda bağımlılıklar hazırlanır,
veritabanı migration'ları uygulanır ve ilk yönetici hesabı için yönlendirme yapılır.
Servisler hazır olup HTTP yanıtları doğrulandıktan sonra tarayıcı açılır.

Geliştirme portlarını değiştirmek için proje klasöründe Komut İstemi açıp çalıştırın:

```bat
start-local.bat --configure
```

Seçimler sonraki açılışlarda yeniden kullanılır. Eski `start-dev.bat` ve
`python launcher.py dev` komutları da kullanılabilir; hızlı başlangıç ayarlarını
değiştirmezler.

## HTTPS production

`start-prod.bat` dosyasına ilk kez çift tıkladığınızda şu bilgiler istenir:

1. Sunucunun IPv4 adresi.
2. HTTPS portu; Enter ile varsayılan `443` seçilir.
3. Repository dışında tutulan PEM sertifika dosyasının yolu.
4. Sertifikayla eşleşen PEM özel anahtar dosyasının yolu.

Sertifika seçilen IPv4 adresini IP SAN alanında içermeli, geçerli olmalı ve
özel anahtar şifresiz olmalıdır. Sertifika zincirine istemcilerin güvenmesi gerekir.
Başlatıcı Windows'un veya tarayıcının sertifika güven ayarlarını otomatik değiştirmez.
Sertifika hazırlama, port izinleri ve native profilin sınırları için
[HTTPS launcher rehberine](launcher-production.md) bakın.

Tamamen yeni kurulumda production env dosyası ve veri dizini repository dışında
oluşturulur. Bağımlılıklar kurulur, arayüz derlenir, migration'lar uygulanır ve ilk
yönetici hesabı için yönlendirme yapılır. HTTPS yanıtı doğrulandıktan sonra tarayıcı
açılır. Bu profil yerel SQLite kullanır; Docker, PostgreSQL/Redis, uzak sunucuya
dağıtım veya Windows servisi kurulumu yapmaz. Mevcut Docker verileri otomatik
taşınmaz.

Normal açılış için yine `start-prod.bat` dosyasına çift tıklayın. Normal production
açılışı **paket kurmaz, frontend derlemez ve migration uygulamaz**. Hazırlık kaydı,
bağımlılıklar veya build güncel değilse hata vererek açık bir hazırlık adımı ister.

Adres, port veya TLS dosyalarının yolunu yeniden seçmek için:

```bat
start-prod.bat --configure
```

`--configure` mevcut env dosyasını yeniden üretmez; güncelleme hazırlığı yerine
geçmez. Var olan kurulumun env ve TLS dosyalarını koruyun.
Komut İstemi'nde `SECRET_KEY` veya `NUMARATOR_DATA_DIR` tanımlıysa hızlı başlangıç
bunları kaldırmanızı ister; production ayarları kayıtlı env dosyasından okunur.

## Ayarlar ve veriler nerede tutulur?

Windows Gezgini'nin adres çubuğuna `%LOCALAPPDATA%\Numarator` yazabilirsiniz.

| Konum | İçerik |
| --- | --- |
| `%LOCALAPPDATA%\Numarator\production.env` | Production ayarları ve üretilen gizli anahtar |
| `%LOCALAPPDATA%\Numarator\data` | Production SQLite veritabanı ve native profilin çalışma dosyaları |
| `%LOCALAPPDATA%\Numarator\launcher\<checkout-id>\settings.json` | Bu proje kopyasının adres, port ve TLS yolu seçimleri; gizli anahtar içermez |
| Aynı klasörde `development.prepared.json` ve `production.prepared.json` | Ortama ait başarılı hazırlık kayıtları; parola veya gizli anahtar içermez |

`<checkout-id>` proje klasörüne göre belirlenir. Yeni bir klasöre kopyalamak o kopya
için ayrı bir ayar/hazırlık kaydı oluşturur; mevcut production verilerini yeni
kurulum saymaz. Var olan env ve veri dosyaları korunur. Env dosyasını, özel anahtarı
ve veri dizinini yalnız uygulamayı çalıştıran hesabın erişebileceği şekilde saklayın.

Bir proje kopyasında aynı anda tek hızlı başlangıç çalışır. İkinci çift tıklama
hata verir; çalışan servislerin kullandığı ortak sanal ortam veya `node_modules`
değiştirilmez. Geliştirme ve production'ı aynı anda çalıştırmak gerekiyorsa ayrı
proje klasörleri kullanın. Aynı production veritabanını birden fazla sunucuyla
açmayın.
Bir profil yeniden hazırlanırken ortak bağımlılıkları kullanan diğer profilin
hazırlık kaydı da geçersiz kılınır; bu profil sonraki kullanımda yeniden hazırlık ister.

## Güncelleme veya mevcut kurulumun hazırlanması

1. Çalışan servisi terminalinde **Ctrl+C** ile durdurun ve kapanmasını bekleyin.
2. Mevcut veri varsa servis kapalıyken `data` dizinini ve `production.env` dosyasını
   yedekleyin; TLS özel anahtarını ayrıca güvenli tutun.
3. Yeni kaynak koduyla açıkça hazırlık çalıştırın:

   ```bat
   start-prod.bat --prepare
   ```

Bu işlem bağımlılıkları hazırlar, frontend'i derler ve gerekli migration'ları
uygular. Sonraki normal açılışlarda `--prepare` kullanmayın. Geliştirme hazırlığını
yenilemek için `start-local.bat --prepare` kullanılabilir.

Başarılı hazırlık kaydı yokken mevcut env veya veri bulunursa otomatik kurulum
yapılmaz; yedek aldıktan sonra açıkça `--prepare` gerekir. **Kayıt bulunmaması,
veritabanının yeni olduğu anlamına gelmez.** Veri mevcutken env dosyası kayıpsa
önce özgün env dosyasını yedekten geri yükleyin; başlatıcı yeni gizli anahtar
üretip mevcut kurulumun üzerine yazmaz.

## Durdurma ve hatalar

Servisler çalışırken terminal açık kalır. **Ctrl+C** alt süreçleri durdurur.
Başlatma hatasında mesajı okuyabilmeniz için pencere tuşa basılana kadar açık
tutulur; komut satırına gerçek hata kodu döner. Başarılı çıkışta ek tuş beklenmez.
Python bulunamazsa Python 3.11+ kurulumunu ve PATH/Python launcher seçimini kontrol
edin. Bağımlılık veya derleme hatasında terminaldeki ayrıntıyı okuyup ilgili
sorunu giderin; production güncellemesini yedek sonrası `--prepare` ile yineleyin.

Hızlı başlangıcın ilk kurulumu çevrimiçidir. Mevcut
[offline paket hazırlama ve kurulum komutları](../README.md#offline-kurulum)
korunur; offline ilk kurulum için bu ayrı akışı kullanın.

Windows komut dosyalarının davranış testleri uygulama servisi açmadan ve proje
bağımlılığı kurmadan geçici Python ortamlarıyla çalışır:

```bat
py -3 -m unittest scripts.test_windows_entrypoints -v
```

Bu testler gerçek `cmd.exe` gerektirir ve macOS/Linux'ta atlanır.
