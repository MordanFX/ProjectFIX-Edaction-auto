import { useState } from "react";

import { getVimeoEmbedUrl } from "../video";

export function VimeoPreview({ url, title }: { url: string | null; title: string }) {
  const [active, setActive] = useState(false);
  const embedUrl = getVimeoEmbedUrl(url);
  if (!embedUrl) return null;

  return (
    <div className="vimeo-preview vimeo-preview--deferred">
      {active ? (
        <iframe
          src={embedUrl}
          title={title}
          allow="autoplay; fullscreen; picture-in-picture"
          allowFullScreen
        />
      ) : (
        <button type="button" onClick={() => setActive(true)}>
          <span>▶</span>
          <strong>Загрузить видеопревью</strong>
          <small>Плеер откроется только по запросу</small>
        </button>
      )}
    </div>
  );
}
