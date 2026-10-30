# Wallqueue

Linux Mint Cinnamon için günlük duvar kağıdı uygulaması. Bing, NASA APOD, Wikimedia,
NASA Image of the Day, ESA/Hubble ve ESO resimlerini bir kuyrukta toplar ve bilgisayar
açıkken seçtiğin aralıkla (1–5 saat) sırayla gösterir.

## Kurulum

```sh
./install.sh
```

Ek paket gerekmez: `python3-requests`, `python3-pil` ve `python3-gi` Mint'te hazır gelir.

## Kullanım

```sh
wallqueue gui      # ayar penceresi
wallqueue next     # sonraki resim
wallqueue status   # kuyruk durumu
wallqueue fetch    # kaynakları hemen tara
journalctl --user -u wallqueue.service   # günlükler
```

## Nasıl çalışır

Sürekli çalışan bir süreç yoktur. systemd zamanlayıcısı 5 dakikada bir `wallqueue tick`
komutunu çalıştırır, komut işini yapıp kapanır:

- Günde bir kez kaynakları tarar; internet yoksa 15 dakikada bir yeniden dener.
- Yalnızca bilgisayarın açık olduğu süreyi sayar. Uyku ve kapalı kalınan süre sayılmaz,
  sayaç yeniden açılışlarda sıfırlanmaz. Seçilen süre dolunca resmi değiştirir.
- Sıradaki 20 resmi indirilmiş tutar, böylece internetsiz günlerde de çalışır.

Kaynaklar sırayla döner ve her kaynak en yeni resmini önce sunar. Kuyruk 20'nin altına
düşerse APOD ve Wikimedia arşivlerinden eski resimler çekilir, kuyruk 200'ü geçerse
sondaki en eski kayıtlar atılır. İnternet de yoksa daha önce gösterilenler yeniden
kullanılır. Disk kullanımı 1 GB'ı geçerse en eski gösterilen dosyalar silinir; ekrandaki
resim ve favoriler silinmez.

Ayarlar `~/.config/wallqueue/config.json`, veriler `~/.local/share/wallqueue/` altındadır.

## Testler

```sh
python3 -m unittest discover -s tests
```
