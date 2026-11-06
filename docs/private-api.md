# Numarator Özel API Entegrasyon Rehberi

Bu API, ERP, CRM, e-ticaret veya belge yönetim sistemi gibi güvenilen sunucu uygulamalarının Numarator'dan numara almasını ve alınan numaranın yaşam döngüsünü yönetmesini sağlar. API tarayıcı kullanıcı API'sinden ayrıdır ve `/api/private/v1/` altında sürümlenir.

## 1. Başlangıç

Her dış uygulama için ayrı bir API anahtarı oluşturun. Anahtar yönetimi yalnızca Numarator'da oturum açmış adminlere (`is_staff=True`) açıktır. Her admin kendi oluşturduğu anahtarları yönetir. Admin olmayan kullanıcılar menüyü göremez, `/settings/api-keys` sayfasına ve yönetim endpointlerine erişemez. Daha önce oluşturulmuş anahtarların dış uygulama erişim davranışı değişmez.

### Arayüzden anahtar oluşturma

1. Admin hesabıyla giriş yapın ve kullanacağınız formatı **Format Yönetimi** ekranından aktif edin.
2. Sol menüden **API Anahtarları → Yeni API Anahtarı** seçeneğini açın.
3. Uygulama adını (ör. `AW Center Local`) girin ve ihtiyaç duyduğu yetkileri seçin.
4. İzin verilecek formatları ad ve kodlarına göre seçin; arayüz UUID değerlerini otomatik gönderir. **Tüm aktif formatlara erişim ver** seçeneği gelecekte aktif edilecek formatları da kapsar.
5. İsteğe bağlı son geçerlilik tarihini tarayıcınızın yerel saat diliminde seçin. Boş bırakırsanız anahtar süresizdir.
6. **Anahtar oluştur** düğmesine basın. Anahtar yalnızca bu pencerede gösterilir; kopyalayıp güvenli yapılandırmanıza kaydedin ve kaydettiğinizi işaretleyerek pencereyi kapatın. Sayfayı yenilemek anahtarı kaybettirir.

AW Center için anahtarı `NUMARATOR_API_KEY` alanına, seçilen formatın **code** değerini `NUMARATOR_PROJECT_FORMATS` içine yazın. UUID yalnızca anahtarın format yetkileri içindir. Env değişikliğinden sonra AW Center'ı yeniden başlatın.

Anahtar listesinde yetkiler, format kodları, son kullanım, son geçerlilik ve iptal durumu görünür. **İptal et** işlemi onaydan sonra anahtarı kalıcı olarak devre dışı bırakır. Anahtarı yenilemek için yenisini oluşturun, dış uygulamada değiştirin ve eskisini iptal edin.

### Yönetim endpointleri

Swagger veya doğrudan API kullanımı da mümkündür; yönetim endpointleri aynı admin kısıtını ve mevcut HttpOnly cookie + CSRF korumasını kullanır.

| İşlem | Endpoint |
| --- | --- |
| Anahtarları listele | `GET /api/v1/integrations/api-keys/` |
| Anahtar oluştur | `POST /api/v1/integrations/api-keys/` |
| Anahtar ayrıntısı | `GET /api/v1/integrations/api-keys/{id}/` |
| Anahtarı kalıcı olarak iptal et | `POST /api/v1/integrations/api-keys/{id}/revoke/` |
| Desteklenen kapsamları listele | `GET /api/v1/integrations/api-keys/scopes/` |

Oluşturma isteği örneği:

```json
{
  "name": "ERP Production",
  "scopes": [
    "formats:read",
    "numbers:generate",
    "numbers:read",
    "numbers:status"
  ],
  "allowed_formats": ["9a15d9a8-07b1-4e5a-9f80-5ac975b11221"],
  "expires_at": "2027-01-01T00:00:00+03:00"
}
```

`scopes` ve `allowed_formats` alanları bilinçsiz geniş yetki verilmesini önlemek için zorunludur. `allowed_formats: []` açıkça gönderilirse anahtar tüm aktif formatlara erişir. En az yetki ilkesi için production anahtarlarında bu listeyi format UUID'leriyle sınırlandırın.

İzin verilen bir formatın silinmesi anahtarın erişimini genişletmez. Listedeki tüm
formatlar silinmişse anahtar başka formatlara erişemez; bu durum açıkça verilen
`allowed_formats: []` izninden farklıdır.

Başarılı cevapta `data.api_key` alanı yalnızca bir kez döner:

```json
{
  "success": true,
  "data": {
    "id": "44609dda-13cc-4f81-84c7-e48ed20f8d93",
    "name": "ERP Production",
    "key_prefix": "dnk_4b580f715ef2",
    "api_key": "dnk_4b580f715ef2_SECRET_PART",
    "active": true
  },
  "message": "API key created. Store it now; it will not be shown again."
}
```

Tam anahtar veritabanına yazılmaz; yalnızca SHA-256 özeti tutulur. Kaybedilen anahtar geri okunamaz, yenisi oluşturulup eskisi iptal edilmelidir.

### Kapsamlar

| Kapsam | Yetki |
| --- | --- |
| `formats:read` | Aktif formatları, gerekli context alanlarını ve önizlemeyi okur. |
| `numbers:generate` | Yeni numara üretir. |
| `numbers:read` | Numara geçmişini okur ve numara doğrular. |
| `numbers:status` | Numarayı `used` veya `cancelled` durumuna geçirir. |

## 2. Kimlik doğrulama

Her özel API isteğinde anahtarı `X-API-Key` header'ında gönderin:

```http
X-API-Key: dnk_4b580f715ef2_SECRET_PART
Accept: application/json
Content-Type: application/json
```

Anahtarı query string'e koymayın; URL'ler proxy, tarayıcı geçmişi ve erişim loglarında kalabilir. Production'da yalnızca HTTPS kullanın.

## 3. Endpoint özeti

| Metot | Endpoint | Kapsam | Açıklama |
| --- | --- | --- | --- |
| `GET` | `/api/private/v1/formats/` | `formats:read` | İzin verilen aktif formatları listeler. |
| `GET` | `/api/private/v1/formats/{code}/` | `formats:read` | Format sözleşmesini ve gerekli context alanlarını döndürür. |
| `POST` | `/api/private/v1/formats/{code}/preview/` | `formats:read` | Sıra tüketmeden örnek numara üretir. |
| `POST` | `/api/private/v1/numbers/` | `numbers:generate` | İdempotent olarak tek numara üretir. |
| `GET` | `/api/private/v1/numbers/` | `numbers:read` | Numara geçmişini filtreleyerek listeler. |
| `GET` | `/api/private/v1/numbers/{id}/` | `numbers:read` | Bir numaranın son durumunu döndürür. |
| `POST` | `/api/private/v1/numbers/validate/` | `numbers:read` | Metin olarak verilen numaranın varlık/geçerlilik durumunu döndürür. |
| `PATCH` | `/api/private/v1/numbers/{id}/status/` | `numbers:status` | Aktif numarayı kullanıldı veya iptal edildi yapar. |

Liste endpointleri `page` ve en fazla 100 olacak şekilde `page_size` parametrelerini destekler.

Özel API bilinçli olarak format oluşturma/düzenleme/aktivasyon, sayaç müdahalesi ve toplu üretim endpointi açmaz. Bunlar yüksek etkili yönetim işlemleridir ve tarayıcı API'sinin cookie + CSRF korumasında kalır. Dış uygulamalar her iş olayı için tek, idempotent üretim isteği yapmalıdır; bu yaklaşım kısmi toplu işlem hatalarında hangi numaranın tüketildiğini belirsiz bırakmaz.

## 4. Format keşfi ve önizleme

```bash
curl --fail-with-body \
  -H "X-API-Key: $NUMARATOR_API_KEY" \
  -H "Accept: application/json" \
  https://numarator.example.com/api/private/v1/formats/ORDER/
```

Format cevabındaki `required_context`, üretim sırasında gönderilebilecek dinamik alanları belirtir:

```json
{
  "success": true,
  "data": {
    "code": "ORDER",
    "name": "Sipariş",
    "preview": "ORD-[BRANCH]-0001",
    "required_context": [
      {"key": "branch", "required": true, "default": null, "max_length": 10}
    ],
    "sequence_reset_period": "yearly"
  }
}
```

Context ile önizleme:

```bash
curl --fail-with-body -X POST \
  -H "X-API-Key: $NUMARATOR_API_KEY" \
  -H "Content-Type: application/json" \
  -d '{"context_data":{"branch":"IST"}}' \
  https://numarator.example.com/api/private/v1/formats/ORDER/preview/
```

Önizleme sıra numarası tüketmez ve kayıt oluşturmaz.

## 5. Numara üretme ve idempotency

`POST /numbers/` için `Idempotency-Key` zorunludur. Bu değer dış sistemdeki tek bir iş olayını temsil etmelidir; örneğin `erp-order-84519`. İzin verilen karakterler harf, rakam, `.`, `_`, `:`, `-`; uzunluk 1-128'dir.

```bash
curl --fail-with-body -X POST \
  -H "X-API-Key: $NUMARATOR_API_KEY" \
  -H "Idempotency-Key: erp-order-84519" \
  -H "Content-Type: application/json" \
  -d '{
    "format_code": "ORDER",
    "context_data": {"branch": "IST"},
    "metadata": {"customer_id": 42},
    "external_reference": "84519"
  }' \
  https://numarator.example.com/api/private/v1/numbers/
```

İlk başarılı istek `201 Created` döner:

```json
{
  "success": true,
  "data": {
    "id": 1821,
    "document_number": "ORD-IST-2026-01821",
    "format_code": "ORDER",
    "status": "active",
    "valid": true,
    "external_reference": "84519",
    "context_data": {"branch": "IST"},
    "metadata": {"customer_id": 42},
    "generated_at": "2026-09-01T12:40:31.128Z"
  }
}
```

Aynı API anahtarı, aynı `Idempotency-Key` ve aynı gövdeyle yapılan tekrar aynı kaydı `200 OK` ve `Idempotent-Replayed: true` header'ıyla döndürür. Aynı idempotency anahtarının farklı bir gövdeyle kullanılması `409 Conflict` üretir. Timeout sonrasında yeni anahtar üretmeyin; aynı anahtarla isteği güvenle tekrarlayın.

Başarılı üretimden sonra formatın arşivlenmesi veya zorunlu context alanlarının
değişmesi kayıtlı sonucu tekrar almayı engellemez. Yeni üretim istekleri güncel
format kurallarına tabidir. Tekrar istekleri de anahtarın güncel geçerlilik,
scope ve format erişim kontrollerinden geçer; iptal edilmiş veya erişimi
kaldırılmış bir anahtar eski sonucu alamaz.

`context_data` yalnızca string, number ve boolean değer kabul eder ve en fazla 8 KiB olabilir. `metadata` geçerli JSON nesnesi olmalı ve en fazla 16 KiB olabilir. Parola, token veya gereksiz kişisel veri göndermeyin.

## 6. Mutabakat, doğrulama ve durum yönetimi

Geçmişi dış referansla sorgulama:

```http
GET /api/private/v1/numbers/?format_code=ORDER&external_reference=84519
```

Desteklenen filtreler:

- `format_code`
- `document_number` (tam eşleşme)
- `external_reference` (tam eşleşme)
- `status`
- `generated_from` ve `generated_to` (ISO-8601 date-time)
- `page` ve `page_size`

Numaranın `/` gibi URL ayraçları içerebilmesi nedeniyle metinle doğrulama path parametresi yerine JSON gövdesi kullanır:

```bash
curl --fail-with-body -X POST \
  -H "X-API-Key: $NUMARATOR_API_KEY" \
  -H "Content-Type: application/json" \
  -d '{"document_number":"ORD/IST/2026/01821"}' \
  https://numarator.example.com/api/private/v1/numbers/validate/
```

`valid` yalnızca durum `active` iken `true` olur. `used`, `cancelled` ve `expired` numaralar vardır fakat geçerli değildir.

Kullanıldı olarak işaretleme:

```http
PATCH /api/private/v1/numbers/1821/status/
Content-Type: application/json

{"status":"used"}
```

İptal etme:

```json
{"status":"cancelled","reason":"ERP siparişi iptal edildi"}
```

Durum geçişi yalnızca `active -> used` veya `active -> cancelled` olabilir. Aynı durum isteğini tekrarlamak güvenlidir ve `200` döner; farklı bir terminal duruma geçirme denemesi `409` döner.

## 7. Hata sözleşmesi

Hatalar ortak bir zarfla döner:

```json
{
  "success": false,
  "error": {
    "code": 409,
    "message": "This Idempotency-Key was already used with a different request body.",
    "details": {"detail": "..."}
  }
}
```

| HTTP | Anlamı | İstemci davranışı |
| --- | --- | --- |
| `400` | Gövde, filtre veya header doğrulama hatası | İsteği düzeltin; aynen retry etmeyin. |
| `401` | Anahtar eksik, hatalı, süresi dolmuş veya iptal edilmiş | Anahtarı/secret kaydını kontrol edin. |
| `403` | Gerekli kapsam yok | Anahtar yetkisini yöneticiden isteyin. |
| `404` | Kayıt yok veya anahtarın format izni yok | Kod/kimlik ve format iznini kontrol edin. |
| `409` | Idempotency veya yaşam döngüsü çakışması | Mevcut kaydı okuyup iş akışını uzlaştırın. |
| `422` | Format verilen verilerle numara üretemedi | Format/context sözleşmesini kontrol edin. |
| `429` | Hız limiti aşıldı | `Retry-After` kadar exponential backoff uygulayın. |
| `500` | Beklenmeyen sunucu hatası | Aynı idempotency anahtarıyla kontrollü retry yapın. |

Her cevapta bulunan `X-Request-ID` değerini hata kaydı ve destek taleplerinde saklayın.

## 8. Hız limitleri ve operasyon

Varsayılan limitler anahtar başınadır:

- Tüm özel API: `5000/hour`
- Numara üretme: `1000/minute`

Değerler `REST_FRAMEWORK.DEFAULT_THROTTLE_RATES` içinden deployment gereksinimine göre değiştirilebilir.

Production önerileri:

1. Her uygulama ve ortam için ayrı anahtar kullanın; test ve production anahtarlarını paylaşmayın.
2. Anahtarı secret manager'da tutun, kaynak koda veya loga yazmayın.
3. Kapsamları ve `allowed_formats` listesini gereken minimumla sınırlandırın.
4. Son kullanma tarihi belirleyin; rotasyonda önce yeni anahtarı devreye alın, sonra eskisini iptal edin.
5. `external_reference`, dönen `id`, `document_number` ve `X-Request-ID` alanlarını dış sistem işlem kaydıyla ilişkilendirin.
6. Retry sırasında aynı `Idempotency-Key` ve birebir aynı JSON anlamını koruyun.

Güncel ve makine tarafından okunabilir sözleşme `/api/schema/`, etkileşimli görünüm `/api/docs/` adresindedir.
