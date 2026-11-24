# Wallqueue

<img src="data/icons/wallqueue.svg" alt="" width="96" align="right">

A daily wallpaper app for Linux Mint Cinnamon. It collects images from Bing, NASA APOD,
Wikimedia, NASA Image of the Day, ESA/Hubble and ESO into a queue, then shows them in turn
at an interval you choose (1–5 hours of computer use). If the
[Ezan Vakti](#ezan-vakti) app is installed, its hand-picked Islamic pictures join the
rotation too.

The settings window is currently in Turkish.

## Requirements

- Linux Mint or another desktop running Cinnamon
- systemd user services
- `python3-requests`, `python3-pil` and `python3-gi`, which Mint ships by default

No API keys are needed.

## Installation

```sh
git clone https://github.com/fatihebrarinan/background-images.git
cd background-images
./install.sh
```

The installer points at the cloned folder, so run it again if you move the project.

## Usage

```sh
wallqueue gui      # settings window
wallqueue next     # show the next wallpaper (--notify: also as a notification)
wallqueue status   # print the queue state
wallqueue fetch    # check the sources now
wallqueue add PATH [--title T] [--credit C] [--page-url U] [--now]
                   # queue a picture from disk as the next wallpaper
wallqueue focus SOURCE [--today]
                   # switch to one source's pictures and show them first
wallqueue focus off
journalctl --user -u wallqueue.service   # logs
```

From the settings window you can change the interval, turn sources on or off, put one source
first, skip an image, mark it as a favorite, or ban it. Right-clicking the desktop also offers
**Sonraki duvar kâğıdı** (next wallpaper), which switches without opening the window and names
the new picture in a notification.

### Focus on one source

`wallqueue focus islami --today` (or **Önce göster** in the settings window) switches the
wallpaper to one of that source's pictures right away and shows its pictures before all others
from then on, for example to see only Islamic pictures today. If the wallpaper already comes
from that source, it stays until its time is up. The
sources are `bing`, `apod`, `wikimedia`, `nasa_iotd`, `hubble`, `eso` and `islami`. With
`--today` (**Sadece bugün**) the focus ends at midnight; without it, it lasts until
`wallqueue focus off`.

It means "first", not "only": when the source has no downloaded picture left, the others
follow as usual, so the wallpaper never gets stuck. While a source is in focus, Wallqueue keeps
five of its pictures downloaded and refills it from its archive when it runs low, even if the
other sources keep the queue full. Turning the source off ends the focus. Pictures added with
`wallqueue add` still come first, and a focus you choose takes the place of the Ezan Vakti
[theme days](#ezan-vakti).

`wallqueue add` copies a picture into Wallqueue's own folder (the original is left alone) and
puts it at the front of the queue, so it is shown when the current interval ends, or at once
with `--now`. The most recent addition goes first. Since you picked it yourself, any readable
image is accepted; one that is not landscape-shaped gets a warning, because the desktop will
crop it. Adding the same file again does not create a second entry, it just moves the picture
back to the front.

## How it works

There is no long-running process. A systemd timer runs `wallqueue tick` every five minutes,
and the command does what is due and exits:

- It checks the sources once a day and retries every 15 minutes while offline.
- It counts only the time the computer is on. Sleep and shutdown do not count, and the
  counter is not reset by a restart. When the chosen time has passed, the wallpaper changes.
- It keeps the next 20 images downloaded, so offline days still work.

Sources take turns, and each one offers its newest image first. Images that are not landscape
or are smaller than 1920×1000 are skipped, as are videos and duplicates.

The queue is designed never to run dry:

1. The next unseen image is shown.
2. Below 20 waiting images, older images are pulled from the APOD and Wikimedia archives.
3. If nothing new can be reached, previously shown images are reused.
4. If there are no images at all, the current wallpaper stays.

Above 200 waiting images, the oldest entries are dropped from the tail. Above 1 GB of disk use,
the files shown longest ago are deleted. The current image and favorites are never deleted.

Settings live in `~/.config/wallqueue/config.json` and data in `~/.local/share/wallqueue/`.
The timer, the desktop menu and the settings window take turns through a lock file there, so
two of them never change the wallpaper at the same moment.

The installer also puts the app icon in `~/.local/share/icons/hicolor/` and the desktop menu
entry in `~/.local/share/nemo/actions/wallqueue-next.nemo_action`. The menu entry needs Nemo
to draw the desktop, which is the Cinnamon default; it is not shown when desktop icons are
turned off in Nemo.

## Ezan Vakti

Wallqueue works together with the Ezan Vakti prayer times app without depending on it. Neither
app imports the other; they share only these files and one command:

| What | Path | Written by |
| --- | --- | --- |
| Picture list | `${XDG_DATA_HOME:-~/.local/share}/ezan-vakti/resimler.json` | Ezan Vakti |
| Today's hint | `${XDG_CACHE_HOME:-~/.cache}/ezan-vakti/bugun.json` | Ezan Vakti |
| `wallqueue add PATH …` | | called by Ezan Vakti |

**The "İslami resimler (Ezan Vakti)" source** (`islami`) reads the picture list: about a
hundred Wikimedia Commons pictures of mosques, interiors, calligraphy, illumination and tiles,
each with its author and license, which Wallqueue shows as the credit. It is on by default and
can be turned off in the settings window like any other source. If the file is missing or
broken, the source simply offers nothing.

The list is not a feed, so the source gives it a schedule: one picture is "published" each
day, in a fixed shuffled order, and the cycle starts again once every picture has had its day.
Each daily check adds about one new picture, and when the queue runs low the source hands out
earlier pictures of the cycle seven at a time, like the APOD and Wikimedia archives. The source
therefore takes its turn like the others and never floods the queue, and the whole list comes
through within one cycle. Pictures that are not landscape-shaped are skipped, as for every
source. Because the list is a local file, reading it does not count as being online, so the
15-minute retries still happen while the network is down.

**Theme days.** `bugun.json` carries at least `"tarih": "YYYY-MM-DD"` (a local date) and
`"islami_tema": true|false`; other fields are ignored. When its date is today and
`islami_tema` is true (Ramadan, the holy nights, the Eids), the next wallpaper is a downloaded
Islamic picture whenever one is ready: a theme day works like a [focus](#focus-on-one-source)
on `islami` for that day. When none is ready, the normal order applies. A missing or stale
hint, or turning the `islami` source off, leaves Wallqueue as it is. `wallqueue status` shows
a `Theme:` line on those days. Pictures added with `wallqueue add` still come first, and a
focus you set yourself replaces the theme.

## License

The code is released under the [MIT License](LICENSE).

Wallqueue downloads images for personal use on your own desktop. The images belong to their
respective owners and are not covered by this license; check each source's terms before
reusing them elsewhere.

## Tests

```sh
python3 -m unittest discover -s tests -t .
```
