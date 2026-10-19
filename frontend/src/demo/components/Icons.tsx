type P = { size?: number; color?: string };

const base = (size: number) => ({ width: size, height: size, viewBox: "0 0 24 24", fill: "none", "aria-hidden": true as const });

export function IconChats({ size = 24, color = "currentColor" }: P) {
  return (
    <svg {...base(size)} stroke={color} strokeWidth={2} strokeLinejoin="round">
      <path d="M4 5h16v11H9l-5 4z" />
    </svg>
  );
}

export function IconCheck({ size = 24, color = "currentColor" }: P) {
  return (
    <svg {...base(size)} stroke={color} strokeWidth={2} strokeLinecap="round" strokeLinejoin="round">
      <rect x="4" y="4" width="16" height="16" rx="3" />
      <path d="M8 12l3 3 5-6" />
    </svg>
  );
}

export function IconToday({ size = 24, color = "currentColor" }: P) {
  return (
    <svg {...base(size)} stroke={color} strokeWidth={2}>
      <rect x="4" y="4" width="7" height="7" rx="2" />
      <rect x="13" y="4" width="7" height="7" rx="2" />
      <rect x="4" y="13" width="7" height="7" rx="2" />
      <rect x="13" y="13" width="7" height="7" rx="2" />
    </svg>
  );
}

export function IconGear({ size = 24, color = "currentColor" }: P) {
  return (
    <svg {...base(size)} stroke={color} strokeWidth={2} strokeLinecap="round">
      <circle cx="12" cy="12" r="3" />
      <path d="M12 3v3M12 18v3M3 12h3M18 12h3M5.6 5.6l2.1 2.1M16.3 16.3l2.1 2.1M5.6 18.4l2.1-2.1M16.3 7.7l2.1-2.1" />
    </svg>
  );
}

export function IconBack({ size = 24, color = "currentColor" }: P) {
  return (
    <svg {...base(size)} stroke={color} strokeWidth={2.2} strokeLinecap="round" strokeLinejoin="round">
      <path d="M15 5l-7 7 7 7" />
    </svg>
  );
}

export function IconSend({ size = 22, color = "currentColor" }: P) {
  return (
    <svg {...base(size)} stroke={color} strokeWidth={2.2} strokeLinecap="round" strokeLinejoin="round">
      <path d="M5 12h13M13 6l6 6-6 6" />
    </svg>
  );
}

export function IconLock({ size = 12, color = "currentColor" }: P) {
  return (
    <svg {...base(size)} stroke={color} strokeWidth={2}>
      <rect x="5" y="11" width="14" height="10" rx="2" />
      <path d="M8 11V7a4 4 0 0 1 8 0v4" />
    </svg>
  );
}
