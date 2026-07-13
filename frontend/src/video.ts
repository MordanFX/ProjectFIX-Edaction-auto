export function getVimeoEmbedUrl(reference: string | null | undefined): string | null {
  if (!reference) return null;

  try {
    const url = new URL(reference);
    const hostname = url.hostname.toLowerCase().replace(/^www\./, "");
    if (hostname === "player.vimeo.com") {
      const match = url.pathname.match(/^\/video\/(\d+)/);
      return match ? url.toString() : null;
    }
    if (hostname !== "vimeo.com") return null;

    const parts = url.pathname.split("/").filter(Boolean);
    const videoIndex = parts.findIndex((part) => /^\d+$/.test(part));
    if (videoIndex === -1) return null;

    const videoId = parts[videoIndex];
    const privacyHash = parts[videoIndex + 1];
    const embed = new URL(`https://player.vimeo.com/video/${videoId}`);
    if (privacyHash && /^[a-zA-Z0-9]+$/.test(privacyHash)) {
      embed.searchParams.set("h", privacyHash);
    }
    return embed.toString();
  } catch {
    return null;
  }
}
