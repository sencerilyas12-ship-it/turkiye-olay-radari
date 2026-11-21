
import json
import sys
from pathlib import Path
from datetime import datetime
from urllib.parse import urlparse

ENVANTER = Path("kaynaklar_ek.json")
RAPOR = Path("kaynak_envanter_kontrol_raporu.json")

def rapor_yaz(veri):
    RAPOR.write_text(
        json.dumps(veri, ensure_ascii=False, indent=2),
        encoding="utf-8"
    )

def main():
    hatalar = []
    uyarilar = []

    if not ENVANTER.exists():
        print("HATA: kaynaklar_ek.json bulunamadı.")
        return 1

    try:
        veri = json.loads(ENVANTER.read_text(encoding="utf-8"))
    except Exception as hata:
        print(f"HATA: JSON okunamadı: {hata}")
        return 1

    zorunlu = [
        "surum", "proje", "ayarlar", "iller",
        "kaynak_turleri", "resmi_dizinler",
        "kaynaklar", "ilce_kapsami",
        "haber_toplama_kapsami", "dogrulama_kurallari"
    ]

    for alan in zorunlu:
        if alan not in veri:
            hatalar.append(f"Eksik zorunlu alan: {alan}")

    ayarlar = veri.get("ayarlar", {})
    dogrulama = veri.get("dogrulama_kurallari", {})
    haber = veri.get("haber_toplama_kapsami", {})

    if ayarlar.get("mevcut_dosya_degistirilmeyecek") is not True:
        hatalar.append("Mevcut dosyaları koruma ayarı açık olmalı.")

    if ayarlar.get("otomatik_kaynak_ekleme") is not True:
        hatalar.append("Otomatik kaynak ekleme açık olmalı.")

    if ayarlar.get("otomatik_aktiflestirme") is not True:
        hatalar.append("Otomatik kaynak aktifleştirme açık olmalı.")

    if ayarlar.get("dogrulanmamis_kaynaktan_haber_toplama") is not True:
        hatalar.append("Doğrulanmamış kaynaklardan haber toplama açık olmalı.")

    if ayarlar.get("dogrulanmamis_haberleri_yayinla") is not True:
        hatalar.append("Doğrulanmamış haberlerin yayını açık olmalı.")

    if ayarlar.get("haberleri_otomatik_yayinla") is not True:
        hatalar.append("Otomatik haber yayını açık olmalı.")

    if dogrulama.get("robots_txt_kontrolu") is not True:
        hatalar.append("robots.txt kontrolü açık olmalı.")

    if haber.get("otomatik_yayin") is not True:
        hatalar.append("Haber otomatik yayın ayarı açık olmalı.")

    if haber.get("hukuki_yayin_kurallari", {}).get("masumiyet_karinesi") is not True:
        hatalar.append("Masumiyet karinesi kuralı açık olmalı.")

    iller = veri.get("iller", [])
    plakalar = [il.get("plaka") for il in iller if isinstance(il, dict)]

    if len(iller) != 81:
        hatalar.append(f"81 il bekleniyordu, bulunan: {len(iller)}")

    if sorted(plakalar) != list(range(1, 82)):
        hatalar.append("İl plaka kodları eksik veya hatalı.")

    dizinler = veri.get("resmi_dizinler", [])
    for dizin in dizinler:
        adres = dizin.get("url", "")
        if not adres.startswith("https://"):
            hatalar.append(f"Geçersiz resmî dizin adresi: {adres}")

    kaynaklar = veri.get("kaynaklar", [])
    kaynak_idleri = set()
    kaynak_adresleri = set()

    for sira, kaynak in enumerate(kaynaklar, start=1):
        if not isinstance(kaynak, dict):
            hatalar.append(f"{sira}. kaynak kaydı nesne değil.")
            continue

        kaynak_id = kaynak.get("id")
        adres = kaynak.get("url", "")

        if not kaynak_id:
            hatalar.append(f"{sira}. kaynakta ID eksik.")
        elif kaynak_id in kaynak_idleri:
            hatalar.append(f"Tekrarlanan kaynak ID: {kaynak_id}")
        else:
            kaynak_idleri.add(kaynak_id)

        if not adres:
            hatalar.append(f"{sira}. kaynakta URL eksik.")
        else:
            parca = urlparse(adres)
            if parca.scheme not in ("http", "https") or not parca.netloc:
                hatalar.append(f"Geçersiz kaynak URL: {adres}")
            if adres in kaynak_adresleri:
                hatalar.append(f"Tekrarlanan kaynak URL: {adres}")
            kaynak_adresleri.add(adres)

        if kaynak.get("durum") not in (
            "aday", "aktif", "pasif", "beklemede", "devre_disi"
        ):
            hatalar.append(f"Geçersiz kaynak durumu: {kaynak_id}")

    if veri.get("ilce_kapsami", {}).get("ilce_listesi_tamamlandi") is not True:
        uyarilar.append("Türkiye'deki ilçe listesi henüz tamamlanmamış.")

    sonuc = {
        "proje": "MIHVER",
        "kontrol_zamani": datetime.now().isoformat(timespec="seconds"),
        "envanter_surumu": veri.get("surum"),
        "il_sayisi": len(iller),
        "resmi_dizin_sayisi": len(dizinler),
        "kaynak_sayisi": len(kaynaklar),
        "otomatik_kaynak_ekleme": ayarlar.get("otomatik_kaynak_ekleme"),
        "otomatik_aktiflestirme": ayarlar.get("otomatik_aktiflestirme"),
        "dogrulanmamis_haber_toplama": ayarlar.get("dogrulanmamis_kaynaktan_haber_toplama"),
        "otomatik_yayin": ayarlar.get("haberleri_otomatik_yayinla"),
        "hata_sayisi": len(hatalar),
        "uyari_sayisi": len(uyarilar),
        "hatalar": hatalar,
        "uyarilar": uyarilar,
        "sonuc": "hata_var" if hatalar else "basarili"
    }

    rapor_yaz(sonuc)

    print("MIHVER ENVANTER KONTROLÜ")
    print(f"İl sayısı: {len(iller)}")
    print(f"Resmî dizin: {len(dizinler)}")
    print(f"Kaynak: {len(kaynaklar)}")
    print(f"Hata: {len(hatalar)}")
    print(f"Uyarı: {len(uyarilar)}")

    for hata in hatalar:
        print("HATA:", hata)

    for uyari in uyarilar:
        print("UYARI:", uyari)

    print("Sonuç:", sonuc["sonuc"])
    return 1 if hatalar else 0

if __name__ == "__main__":
    sys.exit(main())
