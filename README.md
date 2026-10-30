# Wallqueue

A daily wallpaper app for Linux Mint Cinnamon. It collects images from Bing, NASA APOD,
Wikimedia, NASA Image of the Day, ESA/Hubble and ESO into a queue, then shows them in turn
at an interval you choose (1–5 hours of computer use).

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
wallqueue next     # show the next wallpaper
wallqueue status   # print the queue state
wallqueue fetch    # check the sources now
journalctl --user -u wallqueue.service   # logs
```

From the settings window you can change the interval, turn sources on or off, skip an image,
mark it as a favorite, or ban it.

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

## License

The code is released under the [MIT License](LICENSE).

Wallqueue downloads images for personal use on your own desktop. The images belong to their
respective owners and are not covered by this license; check each source's terms before
reusing them elsewhere.

## Tests

```sh
python3 -m unittest discover -s tests -t .
```
