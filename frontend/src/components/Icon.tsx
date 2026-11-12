export type IconName = "menu" | "close" | "play" | "plus" | "video" | "clock" | "list" | "layers" | "bulb" | "arrow" | "spark";

export default function Icon({ name, size = 20 }: { name: IconName; size?: number }) {
  return (
    <svg width={size} height={size} viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.8" strokeLinecap="round" strokeLinejoin="round" aria-hidden="true">
      {name === "menu" && <path d="M4 6h16M4 12h16M4 18h16" />}
      {name === "close" && <path d="m6 6 12 12M18 6 6 18" />}
      {name === "play" && <path d="m9 5 11 7-11 7Z" fill="currentColor" stroke="none" />}
      {name === "plus" && <path d="M12 5v14M5 12h14" />}
      {name === "video" && <><rect x="3" y="5" width="18" height="14" rx="3" /><path d="m10 9 5 3-5 3Z" /></>}
      {name === "clock" && <><circle cx="12" cy="12" r="9" /><path d="M12 7v5l3 2" /></>}
      {name === "list" && <><path d="M9 6h11M9 12h11M9 18h11" /><path d="M4 6h.01M4 12h.01M4 18h.01" strokeWidth="3" /></>}
      {name === "layers" && <><path d="m12 3 9 5-9 5-9-5 9-5ZM3 12l9 5 9-5M3 16l9 5 9-5" /></>}
      {name === "bulb" && <><path d="M9 18h6M10 21h4M8 13a6 6 0 1 1 8 0c-1 1-1 2-1 3H9c0-1 0-2-1-3Z" /></>}
      {name === "arrow" && <path d="M7 17 17 7M7 7h10v10" />}
      {name === "spark" && <path d="m12 3 2.5 6.5L21 12l-6.5 2.5L12 21l-2.5-6.5L3 12l6.5-2.5Z" />}
    </svg>
  );
}
