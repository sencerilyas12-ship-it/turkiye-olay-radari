
import os
import re
import json
import time
import hashlib
import urllib.parse
import urllib.request
import urllib.error
import xml.etree.ElementTree as ET

from datetime import datetime, timezone
from email.utils import parsedate_to_datetime
from html import unescape

BASE = os.path.dirname(os.path.abspath(__file__))

DOSYALAR = {
    "envanter": os.path.join(BASE, "kaynaklar_ek.json"),
    "kaynaklar": os.path.join(BASE, "kaynaklar.json"),
    "haberler": os.path.join(BASE, "haberler.json"),
    "durum": os.path.join(BASE, "tarama_durumu.json"),
    "ilceler": os.path.join(BASE, "ilceler.json"),
}

USER_AGENT = "MIHVER-NewsMonitor/3.0"
TIMEOUT = 20

# Her çalışmada ele alınacak yeni sorgu sayısı.
MAX_SORGU = 300

# Sorgular arasındaki bekleme.
BEKLEME = 0.25

# Başarısız sorguların yeniden denenme sayısı.
TEKRAR_DENEME = 2

# Bir sorgu için en fazla bekleme.
MAX_BEKLEME = 8

KONULAR = [
    '"mahkeme" OR "duruşma" OR "adliye" OR "başsavcılık"',
    '"belediye" OR "ihale" OR "meclis kararı" OR "imar"',
    '"kamu görevlisi" OR "soruşturma" OR "denetim" OR "usulsüzlük"',
    '"vatandaş şikayeti" OR "yerel gündem" OR "basın açıklaması"',
    '"tutuklama" OR "gözaltı" OR "mahkeme kararı"',
    '"kamu zararı" OR "yolsuzluk iddiası" OR "kamu ihalesi"'
]

HARIC_TERIMLER = [
    "uyuşturucu",
    "siber suç",
    "trafik kazası",
    "kayıp şahıs",
    "kayıp kişi"
]


def simdi():
    return datetime.now(timezone.utc).isoformat()


def oku(dosya, varsayilan):
    try:
        with open(dosya, "r", encoding="utf-8") as f:
            return json.load(f)
    except FileNotFoundError:
        return varsayilan
    except json.JSONDecodeError as hata:
        raise RuntimeError(
            f"JSON hatası: {dosya}: {hata}"
        )


def yaz(dosya, veri):
    gecici = dosya + ".tmp"

    with open(gecici, "w", encoding="utf-8") as f:
        json.dump(
            veri,
            f,
            ensure_ascii=False,
            indent=2
        )

    os.replace(gecici, dosya)


def indir(url):
    istek = urllib.request.Request(
        url,
        headers={
            "User-Agent": USER_AGENT,
            "Accept": "application/rss+xml, application/xml, text/xml"
        }
    )

    with urllib.request.urlopen(
        istek,
        timeout=TIMEOUT
    ) as cevap:
        return cevap.read()


def indir_guvenli(url):
    son_hata = None

    for deneme in range(TEKRAR_DENEME + 1):
        try:
            return indir(url), None

        except urllib.error.HTTPError as hata:
            son_hata = hata

            if hata.code == 429:
                bekleme = min(
                    3 * (deneme + 1),
                    MAX_BEKLEME
                )

                print(
                    f"429 hız sınırı. "
                    f"{bekleme} saniye sonra tekrar denenecek."
                )

                if deneme < TEKRAR_DENEME:
                    time.sleep(bekleme)
                    continue

            elif 500 <= hata.code < 600:
                bekleme = min(
                    2 * (deneme + 1),
                    MAX_BEKLEME
                )

                if deneme < TEKRAR_DENEME:
                    time.sleep(bekleme)
                    continue

            break

        except Exception as hata:
            son_hata = hata

            if deneme < TEKRAR_DENEME:
                time.sleep(2 * (deneme + 1))
                continue

            break

    return None, son_hata


def temizle(metin):
    metin = unescape(metin or "")
    metin = re.sub(r"<[^>]+>", " ", metin)

    return re.sub(
        r"\s+",
        " ",
        metin
    ).strip()


def tarih_duzenle(deger):
    if not deger:
        return simdi()

    try:
        tarih = parsedate_to_datetime(deger)

        if tarih.tzinfo is None:
            tarih = tarih.replace(
                tzinfo=timezone.utc
            )

        return tarih.astimezone(
            timezone.utc
        ).isoformat()

    except Exception:
        pass

    try:
        tarih = datetime.fromisoformat(
            deger.replace("Z", "+00:00")
        )

        if tarih.tzinfo is None:
            tarih = tarih.replace(
                tzinfo=timezone.utc
            )

        return tarih.astimezone(
            timezone.utc
        ).isoformat()

    except Exception:
        return simdi()


def kimlik(link, baslik):
    veri = (link or baslik).strip().lower()

    return hashlib.sha256(
        veri.encode("utf-8")
    ).hexdigest()


def kategori(baslik, aciklama):
    metin = (
        baslik + " " + aciklama
    ).lower()

    if any(x in metin for x in [
        "duruşma",
        "mahkeme",
        "karar açıklandı"
    ]):
        return "Mahkeme ve Duruşma"

    if any(x in metin for x in [
        "belediye",
        "meclis",
        "imar"
    ]):
        return "Yerel Yönetim"

    if any(x in metin for x in [
        "ihale",
        "kamu zararı",
        "yolsuzluk"
    ]):
        return "Kamu ve İhale"

    if any(x in metin for x in [
        "tutuklama",
        "gözaltı",
        "başsavcılık"
    ]):
        return "Adli Gelişmeler"

    if any(x in metin for x in [
        "cinayet",
        "şüpheli ölüm"
    ]):
        return "Asayiş ve Adli Olaylar"

    return "Yerel Gündem"


def uygun(baslik, aciklama):
    metin = (
        baslik + " " + aciklama
    ).lower()

    return (
        len(baslik.strip()) >= 12
        and not any(
            x in metin
            for x in HARIC_TERIMLER
        )
    )


def ilceleri_yukle():
    veri = oku(
        DOSYALAR["ilceler"],
        None
    )

    if not isinstance(veri, dict):
        raise RuntimeError(
            "ilceler.json okunamadı."
        )

    sehirler = veri.get("cities", [])
    ilceler = veri.get("districts", [])

    sehir_esleme = {}

    for sehir in sehirler:
        try:
            sehir_esleme[
                int(sehir["Id"])
            ] = str(
                sehir["name"]
            ).strip()

        except (
            KeyError,
            TypeError,
            ValueError
        ):
            continue

    sonuc = []
    gorulen = set()

    for kayit in ilceler:
        try:
            il = sehir_esleme[
                int(kayit["cityId"])
            ]

            ilce = str(
                kayit["name"]
            ).strip()

        except (
            KeyError,
            TypeError,
            ValueError
        ):
            continue

        anahtar = (
            il.casefold(),
            ilce.casefold()
        )

        if ilce and anahtar not in gorulen:
            sonuc.append({
                "il": il,
                "ilce": ilce
            })

            gorulen.add(anahtar)

    if not sonuc:
        raise RuntimeError(
            "İlçe listesi boş."
        )

    print(
        "Şehir sayısı:",
        len(sehir_esleme)
    )

    print(
        "Okunan benzersiz ilçe sayısı:",
        len(sonuc)
    )

    if len(sonuc) != 922:
        print(
            "UYARI: İlçe listesi 922 değil:",
            len(sonuc)
        )

    return sonuc


def google_url(il, ilce, konu):
    sorgu = f'"{ilce}" "{il}" {konu}'

    parametre = urllib.parse.urlencode({
        "q": sorgu,
        "hl": "tr",
        "gl": "TR",
        "ceid": "TR:tr"
    })

    return (
        "https://news.google.com/rss/search?"
        + parametre
    )


def haber_olustur(
    baslik,
    link,
    aciklama,
    tarih,
    il,
    ilce,
    kaynak
):
    return {
        "baslik": baslik,
        "aciklama": aciklama[:1200],
        "il": il,
        "ilce": ilce,
        "kategori": kategori(
            baslik,
            aciklama
        ),
        "kaynak": kaynak,
        "tarih": tarih_duzenle(tarih),
        "link": link,
        "durum": "doğrulanmadı",
        "yayinda": True,
        "kimlik": kimlik(
            link,
            baslik
        )
    }


def rss_coz(veri, il, ilce, kaynak):
    bulunan = []

    kok = ET.fromstring(veri)

    for item in kok.findall(".//item"):
        baslik = temizle(
            item.findtext("title", "")
        )

        link = temizle(
            item.findtext("link", "")
        )

        aciklama = temizle(
            item.findtext("description", "")
        )

        tarih = item.findtext(
            "pubDate",
            ""
        )

        if (
            not baslik
            or not link
            or not uygun(baslik, aciklama)
        ):
            continue

        bulunan.append(
            haber_olustur(
                baslik,
                link,
                aciklama,
                tarih,
                il,
                ilce,
                kaynak
            )
        )

    ns = {
        "a": "http://www.w3.org/2005/Atom"
    }

    for entry in kok.findall(
        ".//a:entry",
        ns
    ):
        baslik = temizle(
            entry.findtext(
                "a:title",
                "",
                ns
            )
        )

        aciklama = temizle(
            entry.findtext(
                "a:summary",
                "",
                ns
            )
        )

        tarih = entry.findtext(
            "a:updated",
            "",
            ns
        )

        link_elemani = entry.find(
            "a:link",
            ns
        )

        link = (
            link_elemani.attrib.get(
                "href",
                ""
            )
            if link_elemani is not None
            else ""
        )

        if (
            not baslik
            or not link
            or not uygun(baslik, aciklama)
        ):
            continue

        bulunan.append(
            haber_olustur(
                baslik,
                link,
                aciklama,
                tarih,
                il,
                ilce,
                kaynak
            )
        )

    return bulunan


def rss_oku(url, il, ilce, kaynak):
    veri, hata = indir_guvenli(url)

    if veri is None:
        print(
            "RSS okunamadı:",
            str(hata)[:160]
        )

        return None

    try:
        return rss_coz(
            veri,
            il,
            ilce,
            kaynak
        )

    except Exception as hata:
        print(
            "RSS biçim hatası:",
            str(hata)[:160]
        )

        return None


def kaynaklari_yukle(envanter):
    eski = oku(
        DOSYALAR["kaynaklar"],
        []
    )

    if not isinstance(eski, list):
        eski = []

    sonuc = []

    for kaynak in eski:
        if (
            isinstance(kaynak, dict)
            and kaynak.get("rss")
        ):
            sonuc.append(kaynak)

    ek_kaynaklar = envanter.get(
        "kaynaklar",
        []
    )

    if not isinstance(ek_kaynaklar, list):
        ek_kaynaklar = []

    for kaynak in ek_kaynaklar:
        if not isinstance(kaynak, dict):
            continue

        rss = (
            kaynak.get("rss")
            or kaynak.get("rss_url")
        )

        if rss:
            sonuc.append({
                "ad": (
                    kaynak.get("ad")
                    or kaynak.get("isim")
                    or "Ek kaynak"
                ),
                "il": kaynak.get(
                    "il",
                    "Türkiye"
                ),
                "ilce": kaynak.get(
                    "ilce",
                    ""
                ),
                "rss": rss,
                "kaynak_durumu": kaynak.get(
                    "dogrulama",
                    "doğrulanmadı"
                )
            })

    benzersiz = {}

    for kaynak in sonuc:
        adres = str(
            kaynak.get("rss", "")
        ).strip()

        if adres:
            benzersiz[adres] = kaynak

    return list(
        benzersiz.values()
    )[:150]


def sorgu_coz(sira, ilceler):
    konu_sayisi = len(KONULAR)

    ilce_index = sira // konu_sayisi
    konu_index = sira % konu_sayisi

    il = ilceler[ilce_index]["il"]
    ilce = ilceler[ilce_index]["ilce"]
    konu = KONULAR[konu_index]

    return il, ilce, konu


def ana_islem():
    envanter = oku(
        DOSYALAR["envanter"],
        {}
    )

    haberler = oku(
        DOSYALAR["haberler"],
        []
    )

    durum = oku(
        DOSYALAR["durum"],
        {}
    )

    if not isinstance(envanter, dict):
        raise RuntimeError(
            "kaynaklar_ek.json biçimi hatalı."
        )

    if not isinstance(haberler, list):
        raise RuntimeError(
            "haberler.json liste değil. "
            "Arşiv korunması için işlem durduruldu."
        )

    if not isinstance(durum, dict):
        durum = {}

    ilceler = ilceleri_yukle()

    toplam = (
        len(ilceler) * len(KONULAR)
    )

    baslangic = int(
        durum.get(
            "ilce_arama_sirasi",
            0
        )
    ) % toplam

    # Önce önceki çalışmalardan kalan başarısız
    # sorgular yeniden ele alınır.
    bekleyen = durum.get(
        "basarisiz_sorgular",
        []
    )

    if not isinstance(bekleyen, list):
        bekleyen = []

    bekleyen = sorted({
        int(x)
        for x in bekleyen
        if str(x).isdigit()
        and 0 <= int(x) < toplam
    })

    secilen = bekleyen[:MAX_SORGU]

    # Kalan kapasite yeni sorgularla doldurulur.
    yeni_sorgu_sayisi = (
        MAX_SORGU - len(secilen)
    )

    yeni_siralar = []

    for i in range(yeni_sorgu_sayisi):
        sira = (
            baslangic + i
        ) % toplam

        if sira not in secilen:
            yeni_siralar.append(sira)

    secilen.extend(yeni_siralar)

    yeni_baslangic = (
        baslangic + yeni_sorgu_sayisi
    ) % toplam

    kimlikler = set()

    for haber in haberler:
        if not isinstance(haber, dict):
            continue

        haber_id = (
            haber.get("kimlik")
            or kimlik(
                haber.get("link", ""),
                haber.get("baslik", "")
            )
        )

        kimlikler.add(haber_id)

    yeni_haberler = []

    kaynaklar = kaynaklari_yukle(
        envanter
    )

    rss_basari = 0
    rss_hata = 0

    # Mevcut RSS kaynakları taranır.
    for kaynak in kaynaklar:
        url = str(
            kaynak.get("rss", "")
        ).strip()

        if not url.startswith(
            ("http://", "https://")
        ):
            continue

        sonuc = rss_oku(
            url,
            kaynak.get("il", "Türkiye"),
            kaynak.get("ilce", ""),
            kaynak.get("ad", "Yerel RSS")
        )

        if sonuc is None:
            rss_hata += 1
            continue

        rss_basari += 1
        yeni_haberler.extend(sonuc)

    # Başarısız sorgular sonraki çalışmaya bırakılır.
    basarisiz_yeni = []
    basarili_sorgu = 0

    for sayac, sira in enumerate(secilen, 1):
        il, ilce, konu = sorgu_coz(
            sira,
            ilceler
        )

        print(
            f"İlçe taranıyor: {il} / {ilce} "
            f"({sayac}/{len(secilen)}) "
            f"Sorgu no: {sira + 1}/{toplam}"
        )

        url = google_url(
            il,
            ilce,
            konu
        )

        sonuc = rss_oku(
            url,
            il,
            ilce,
            "Google Haberler RSS"
        )

        if sonuc is None:
            basarisiz_yeni.append(sira)

        else:
            basarili_sorgu += 1
            yeni_haberler.extend(sonuc)

        time.sleep(BEKLEME)

    # Yeni haberler arşive eklenir.
    eklenen = 0

    for haber in yeni_haberler:
        haber_id = haber.get("kimlik")

        if (
            not haber_id
            or haber_id in kimlikler
        ):
            continue

        haberler.append(haber)
        kimlikler.add(haber_id)
        eklenen += 1

    # Eski haberler silinmez ve arşive üst sınır konulmaz.
    haberler.sort(
        key=lambda x: (
            x.get("tarih", "")
            if isinstance(x, dict)
            else ""
        ),
        reverse=True
    )

    # Daha önce bekleyen ancak bu çalışmada
    # yeniden denenmeyen kayıtlar korunur.
    yeniden_bekleyen = [
        x for x in bekleyen
        if x not in secilen
    ]

    yeniden_bekleyen.extend(
        basarisiz_yeni
    )

    yeniden_bekleyen = sorted(
        set(yeniden_bekleyen)
    )

    # Tam tarama yalnızca tüm sorgular
    # başarılı olduğunda tamamlanmış sayılır.
    tam_tarama = (
        yeni_baslangic == 0
        and len(yeniden_bekleyen) == 0
    )

    durum["ilce_arama_sirasi"] = yeni_baslangic
    durum["son_calisma"] = simdi()
    durum["son_eklenen_haber"] = eklenen
    durum["toplam_haber"] = len(haberler)
    durum["ilce_sayisi"] = len(ilceler)
    durum["toplam_sorgu"] = toplam
    durum["toplam_ilce_konu_sorgusu"] = toplam
    durum["bu_calisma_sorgu"] = len(secilen)
    durum["bu_calisma_sorgu_sayisi"] = len(secilen)
    durum["basarili_sorgu"] = basarili_sorgu
    durum["basarisiz_sorgu"] = len(basarisiz_yeni)
    durum["basarisiz_sorgular"] = yeniden_bekleyen
    durum["rss_kaynak_sayisi"] = len(kaynaklar)
    durum["rss_basarili"] = rss_basari
    durum["rss_hata"] = rss_hata
    durum["otomatik_yayin"] = True
    durum["tam_tarama_tamamlandi"] = tam_tarama

    yaz(
        DOSYALAR["haberler"],
        haberler
    )

    yaz(
        DOSYALAR["durum"],
        durum
    )

    print("--------------------------------")
    print("MİHVER taraması tamamlandı.")
    print("İlçe sayısı:", len(ilceler))
    print("Bu çalışmadaki sorgu:", len(secilen))
    print("Başarılı sorgu:", basarili_sorgu)
    print("Başarısız sorgu:", len(basarisiz_yeni))
    print("Bekleyen sorgu:", len(yeniden_bekleyen))
    print("Toplam sorgu:", toplam)
    print("RSS kaynak sayısı:", len(kaynaklar))
    print("RSS başarılı:", rss_basari)
    print("RSS hatalı:", rss_hata)
    print("Yeni haber:", eklenen)
    print("Toplam haber:", len(haberler))
    print("Sonraki tarama sırası:", yeni_baslangic)
    print("Tam tarama tamamlandı:", tam_tarama)
    print("--------------------------------")


if __name__ == "__main__":
    ana_islem()
