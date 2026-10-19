/* Line icons for the desk, 20px on a 24 grid, drawn to match the phone set. */

type P = { size?: number };
const svg = (size: number) => ({ width: size, height: size, viewBox: "0 0 24 24", fill: "none", stroke: "currentColor", strokeWidth: 1.9, strokeLinecap: "round" as const, strokeLinejoin: "round" as const, "aria-hidden": true as const });

export const IHome = ({ size = 20 }: P) => (<svg {...svg(size)}><path d="M4 11l8-7 8 7" /><path d="M6 9.5V20h12V9.5" /><path d="M10 20v-5h4v5" /></svg>);
export const IInbox = ({ size = 20 }: P) => (<svg {...svg(size)}><path d="M4 13l2.5-8h11L20 13v6H4z" /><path d="M4 13h4.5l1 2h5l1-2H20" /></svg>);
export const ISales = ({ size = 20 }: P) => (<svg {...svg(size)}><path d="M4 19V9M10 19V5M16 19v-7M22 19H2" /></svg>);
export const IRupee = ({ size = 20 }: P) => (<svg {...svg(size)}><path d="M7 5h10M7 9h10M7 5c5 0 6 2 6 4s-2 4-6 4l7 6" /></svg>);
export const IUsers = ({ size = 20 }: P) => (<svg {...svg(size)}><circle cx="9" cy="8" r="3.5" /><path d="M2.5 20c.6-3.6 3.2-5.5 6.5-5.5s5.9 1.9 6.5 5.5" /><path d="M16 4.6a3.5 3.5 0 0 1 0 6.8M18 14.8c2 .7 3.2 2.4 3.5 5.2" /></svg>);
export const IBox = ({ size = 20 }: P) => (<svg {...svg(size)}><path d="M3 7.5L12 3l9 4.5v9L12 21l-9-4.5z" /><path d="M3 7.5l9 4.5 9-4.5M12 12v9" /></svg>);
export const IWallet = ({ size = 20 }: P) => (<svg {...svg(size)}><rect x="3" y="6" width="18" height="13" rx="2.5" /><path d="M3 10h18M16 14.5h2" /></svg>);
export const IReport = ({ size = 20 }: P) => (<svg {...svg(size)}><path d="M6 3h9l4 4v14H6z" /><path d="M14 3v5h5M9 17v-3M12 17v-6M15 17v-4" /></svg>);
export const IAgents = ({ size = 20 }: P) => (<svg {...svg(size)}><path d="M12 3v3M8 6h8a3 3 0 0 1 3 3v6a3 3 0 0 1-3 3H8a3 3 0 0 1-3-3V9a3 3 0 0 1 3-3z" /><circle cx="9.5" cy="12" r="1" fill="currentColor" /><circle cx="14.5" cy="12" r="1" fill="currentColor" /><path d="M2 11v3M22 11v3" /></svg>);
export const IGear = ({ size = 20 }: P) => (<svg {...svg(size)}><circle cx="12" cy="12" r="3" /><path d="M12 2.8v2.4M12 18.8v2.4M2.8 12h2.4M18.8 12h2.4M5.5 5.5l1.7 1.7M16.8 16.8l1.7 1.7M5.5 18.5l1.7-1.7M16.8 7.2l1.7-1.7" /></svg>);
export const ISearch = ({ size = 18 }: P) => (<svg {...svg(size)}><circle cx="11" cy="11" r="6.5" /><path d="M16 16l4.5 4.5" /></svg>);
export const IChat = ({ size = 24 }: P) => (<svg {...svg(size)}><path d="M4 5h16v11H9l-5 4z" /><path d="M8.5 10.5h7" /></svg>);
export const IClose = ({ size = 18 }: P) => (<svg {...svg(size)}><path d="M6 6l12 12M18 6L6 18" /></svg>);
export const IArrow = ({ size = 16 }: P) => (<svg {...svg(size)}><path d="M5 12h14M13 6l6 6-6 6" /></svg>);
export const ICheck = ({ size = 16 }: P) => (<svg {...svg(size)}><path d="M5 12.5l4.5 4.5L19 7" /></svg>);
export const IPhone = ({ size = 16 }: P) => (<svg {...svg(size)}><path d="M5 4h4l2 5-2.5 1.5a11 11 0 0 0 5 5L15 13l5 2v4a1 1 0 0 1-1 1A16 16 0 0 1 4 5a1 1 0 0 1 1-1z" /></svg>);
export const ISend = ({ size = 16 }: P) => (<svg {...svg(size)}><path d="M4 12l16-8-6 16-2.5-6.5z" /><path d="M11.5 13.5L20 4" /></svg>);
export const IDownload = ({ size = 16 }: P) => (<svg {...svg(size)}><path d="M12 4v11M7 10.5l5 5 5-5M5 20h14" /></svg>);
export const ISpark = ({ size = 16 }: P) => (<svg {...svg(size)}><path d="M12 3l1.8 5.2L19 10l-5.2 1.8L12 17l-1.8-5.2L5 10l5.2-1.8z" /></svg>);
export const IUndo = ({ size = 16 }: P) => (<svg {...svg(size)}><path d="M9 7L4 12l5 5" /><path d="M4 12h10a6 6 0 0 1 0 12h-2" transform="translate(0 -6)" /></svg>);
