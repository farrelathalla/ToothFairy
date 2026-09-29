"use client";
import { useEffect, useState } from "react";

import { mediaUrl } from "@/lib/api";
import ModelGallery from "./ModelGallery";

/**
 * "Foto Pasien" — the patient's uploaded intraoral views + panoramic, shown as a
 * horizontal slider with the same card + zoom/pan lightbox as ModelGallery.
 *
 * Two sources, in priority order:
 *   1. `images` — the case's real uploads (served from the gateway's authenticated `/media`
 *      mount, so the URL is built by `mediaUrl` which attaches the session token).
 *   2. `base + "inputs.json"` — the dataset's bundled source photos (demos / offline),
 *      served statically from the frontend origin alongside overlays.
 */
const VIEW_LABELS = {
  front: "Tampak Depan",
  side_left: "Samping Kiri",
  side_right: "Samping Kanan",
  up: "Rahang Atas (oklusal)",
  bottom: "Rahang Bawah (oklusal)",
  panoramic: "Panoramik",
};
const ORDER = ["front", "side_left", "side_right", "up", "bottom", "panoramic"];
const rank = (vk) => (ORDER.indexOf(vk) < 0 ? ORDER.length : ORDER.indexOf(vk));

export default function PatientPhotos({ images, base }) {
  const [items, setItems] = useState(null);

  useEffect(() => {
    let alive = true;

    // 1) real uploads on the case
    if (images && images.length) {
      const built = [...images]
        .sort((a, b) => rank(a.view_key) - rank(b.view_key))
        .map((im) => ({
          id: `photo-${im.view_key}`,
          title: VIEW_LABELS[im.view_key] || im.view_key,
          desc: "Foto pasien",
          src: mediaUrl(im.url),
        }));
      setItems(built);
      return;
    }

    // 2) dataset bundled photos
    if (!base) {
      setItems([]);
      return;
    }
    fetch(base + "inputs.json")
      .then((r) => (r.ok ? r.json() : []))
      .then((list) => {
        if (!alive) return;
        setItems(
          (list || [])
            .slice()
            .sort((a, b) => rank(a.view_key) - rank(b.view_key))
            .map((it) => ({
              id: `photo-${it.view_key}`,
              title: VIEW_LABELS[it.view_key] || it.label || it.view_key,
              desc: "Foto pasien",
              src: base + "inputs/" + it.file,
            }))
        );
      })
      .catch(() => alive && setItems([]));

    return () => {
      alive = false;
    };
  }, [images, base]);

  if (!items || !items.length) return null;
  return <ModelGallery title="Foto Pasien" ariaLabel="Foto pasien" items={items} />;
}
