async function loadAd(ad) {
  if (!ad) return;
  ad.hidden = false;
  const rect = ad.getBoundingClientRect();
  if (!rect.width || !rect.height) {
    ad.hidden = true;
    return;
  }
  if (ad.dataset.loaded) return;
  const payload = {
    application: "osap",
    page: {
      type: ad.dataset.pageType || "blog_index",
      entity_type: null,
      entity_id: null,
      language: document.documentElement.lang || "es",
    },
    placement: ad.dataset.adPlacement || "sidebar",
    device: window.innerWidth < 640 ? "mobile" : "desktop",
    mode: "auto_area",
    area: {
      width: Math.max(160, Math.min(2000, Math.round(rect.width))),
      height: Math.max(120, Math.min(1200, Math.round(rect.height))),
    },
    max_ads: 1,
    gap: 0,
    orientation: "auto",
  };
  try {
    const response = await fetch("/ads/compose", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(payload),
    });
    if (response.ok) {
      const fragment = await response.text();
      if (fragment && !fragment.includes('data-layout-status="no-fill"')) {
        ad.innerHTML = fragment;
      }
    }
  } catch {
    // Se conserva el anuncio propio de respaldo.
  }
  ad.dataset.loaded = "1";
}

function showRailAd() {
  return loadAd(document.querySelector(".ad-rail [data-ad]"));
}

if (document.readyState === "loading") {
  document.addEventListener("DOMContentLoaded", () => {
    void showRailAd();
  });
} else {
  void showRailAd();
}
