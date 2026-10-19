/** What changes from one trade to the next: what they sell, in what unit, at
 *  what kind of price, who they sell to and who they buy from. Everything
 *  else in the demo is shared. Rates are typical trade prices, rounded. */

export type ProductSpec = {
  name: string;
  /** Words a visitor might type to mean this item. */
  alias: string[];
  unit: string;
  rate: number;
  /** A typical order, in units. */
  qty: [number, number];
};

export type IndustryPack = {
  id: string;
  label: string;
  products: ProductSpec[];
  /** Combined with a name stem to make customer names. */
  customerKinds: string[];
  suppliers: { name: string; brand: string }[];
  /** One line on what makes this trade different, shown in the details form. */
  note: string;
  /** Delivery or handling line that appears on quotes. */
  terms: string;
  /** Items with a shelf life get expiry wording in stock alerts. */
  expiry?: boolean;
};

export const INDUSTRIES: IndustryPack[] = [
  {
    id: "steel",
    label: "Steel & metals",
    note: "Daily price changes, MT and pieces",
    terms: "Ex-godown · loading included",
    customerKinds: ["Constructions", "Infra", "Fabricators", "Builders", "Engineering", "Steel Traders"],
    suppliers: [
      { name: "Rathi Steel", brand: "JSW" },
      { name: "Sharma Steels", brand: "Tata" },
      { name: "Mahalaxmi Ispat", brand: "SAIL" },
      { name: "Kamdhenu Ltd", brand: "Kamdhenu" },
    ],
    products: [
      { name: "TMT 12mm Fe500D", alias: ["tmt", "12mm", "bar", "rebar", "saria", "sariya"], unit: "MT", rate: 54900, qty: [20, 120] },
      { name: "TMT 16mm Fe500D", alias: ["16mm"], unit: "MT", rate: 54400, qty: [15, 80] },
      { name: "HR coil 2mm", alias: ["hr", "coil", "hrc"], unit: "MT", rate: 58200, qty: [10, 60] },
      { name: "MS angle 50×50×5", alias: ["angle", "ms angle"], unit: "MT", rate: 57100, qty: [5, 30] },
      { name: "MS plate 10mm", alias: ["plate", "ms plate"], unit: "MT", rate: 61500, qty: [5, 40] },
      { name: "GI sheet 0.5mm", alias: ["gi", "sheet"], unit: "MT", rate: 68400, qty: [3, 20] },
    ],
  },
  {
    id: "building",
    label: "Building materials",
    note: "Brand swaps, dealer and contractor prices",
    terms: "Delivered to site · unloading extra",
    customerKinds: ["Builders", "Developers", "Constructions", "Infra", "Contractors", "Realty"],
    suppliers: [
      { name: "UltraTech depot", brand: "UltraTech" },
      { name: "Ambuja dealer", brand: "Ambuja" },
      { name: "Shree Cement CFA", brand: "Shree" },
      { name: "Magicrete", brand: "Magicrete" },
    ],
    products: [
      { name: "OPC 53 cement", alias: ["cement", "opc", "53"], unit: "bag", rate: 385, qty: [500, 4000] },
      { name: "PPC cement", alias: ["ppc"], unit: "bag", rate: 362, qty: [500, 3000] },
      { name: "AAC block 600×200×150", alias: ["aac", "block"], unit: "pc", rate: 62, qty: [2000, 12000] },
      { name: "Tile adhesive 20kg", alias: ["adhesive", "tile"], unit: "bag", rate: 410, qty: [100, 800] },
      { name: "Waterproofing 20L", alias: ["waterproof"], unit: "can", rate: 3650, qty: [10, 80] },
      { name: "Wall putty 40kg", alias: ["putty"], unit: "bag", rate: 720, qty: [100, 600] },
    ],
  },
  {
    id: "electricals",
    label: "Electricals",
    note: "Project quotes with many line items",
    terms: "Delivered · warranty as per brand",
    customerKinds: ["Electricals", "Projects", "Contractors", "Builders", "Engineering", "Infra"],
    suppliers: [
      { name: "Polycab distributor", brand: "Polycab" },
      { name: "Havells CFA", brand: "Havells" },
      { name: "Finolex dealer", brand: "Finolex" },
      { name: "Legrand partner", brand: "Legrand" },
    ],
    products: [
      { name: "FR wire 2.5 sq mm (90 m)", alias: ["wire", "fr", "2.5"], unit: "coil", rate: 2350, qty: [50, 400] },
      { name: "Armoured cable 4C 16 sq mm", alias: ["cable", "armoured"], unit: "m", rate: 410, qty: [200, 2000] },
      { name: "MCB 32A SP", alias: ["mcb"], unit: "pc", rate: 245, qty: [100, 1000] },
      { name: "LED panel 18W", alias: ["led", "panel"], unit: "pc", rate: 420, qty: [100, 800] },
      { name: "Distribution board 8-way", alias: ["db", "board"], unit: "pc", rate: 1650, qty: [20, 150] },
      { name: "Modular switch 6A", alias: ["switch"], unit: "pc", rate: 68, qty: [500, 4000] },
    ],
  },
  {
    id: "pipes",
    label: "Pipes, valves & pumps",
    note: "Sizes, classes and pressure ratings",
    terms: "Delivered · test certificate on request",
    customerKinds: ["Plumbing", "Projects", "Infra", "Engineering", "Irrigation", "Contractors"],
    suppliers: [
      { name: "APL Apollo dealer", brand: "Apollo" },
      { name: "Astral distributor", brand: "Astral" },
      { name: "Kirloskar CFA", brand: "Kirloskar" },
      { name: "Supreme depot", brand: "Supreme" },
    ],
    products: [
      { name: "GI pipe 50mm B class (6 m)", alias: ["gi", "pipe", "50mm"], unit: "length", rate: 2950, qty: [50, 400] },
      { name: "CPVC pipe 1\" (3 m)", alias: ["cpvc"], unit: "length", rate: 610, qty: [100, 800] },
      { name: "HDPE pipe 63mm", alias: ["hdpe"], unit: "m", rate: 168, qty: [500, 3000] },
      { name: "Ball valve 2\"", alias: ["ball", "valve"], unit: "pc", rate: 1850, qty: [20, 150] },
      { name: "CI gate valve 4\"", alias: ["gate"], unit: "pc", rate: 6400, qty: [5, 40] },
      { name: "Monoblock pump 1 HP", alias: ["pump", "monoblock"], unit: "pc", rate: 7900, qty: [5, 40] },
    ],
  },
  {
    id: "hardware",
    label: "Hardware & tools",
    note: "Many small orders, many SKUs",
    terms: "Ex-shop · free delivery above ₹25,000",
    customerKinds: ["Hardware", "Stores", "Traders", "Interiors", "Enterprises", "Agencies"],
    suppliers: [
      { name: "Bosch distributor", brand: "Bosch" },
      { name: "Stanley CFA", brand: "Stanley" },
      { name: "Godrej Locks dealer", brand: "Godrej" },
      { name: "Hettich partner", brand: "Hettich" },
    ],
    products: [
      { name: "Drill machine 13mm", alias: ["drill"], unit: "pc", rate: 2450, qty: [10, 60] },
      { name: "Angle grinder 4\"", alias: ["grinder"], unit: "pc", rate: 2150, qty: [10, 60] },
      { name: "SS screws (box of 100)", alias: ["screw", "screws"], unit: "box", rate: 380, qty: [50, 400] },
      { name: "Door hinges 4\"", alias: ["hinge", "hinges"], unit: "pc", rate: 95, qty: [200, 2000] },
      { name: "Padlock 65mm", alias: ["lock", "padlock"], unit: "pc", rate: 310, qty: [50, 300] },
      { name: "Hand tool kit 24-pc", alias: ["tool", "kit"], unit: "kit", rate: 1250, qty: [10, 80] },
    ],
  },
  {
    id: "chemicals",
    label: "Chemicals",
    note: "Batches, grades and safety documents",
    terms: "Ex-warehouse · MSDS attached",
    customerKinds: ["Industries", "Chemicals", "Pharma", "Textiles", "Processors", "Labs"],
    suppliers: [
      { name: "GACL dealer", brand: "GACL" },
      { name: "Tata Chemicals CFA", brand: "Tata" },
      { name: "Deepak distributor", brand: "Deepak" },
      { name: "Aarti stockist", brand: "Aarti" },
    ],
    products: [
      { name: "Caustic soda flakes", alias: ["caustic", "soda flakes", "naoh"], unit: "kg", rate: 48, qty: [2000, 20000] },
      { name: "Soda ash light", alias: ["soda ash", "ash"], unit: "kg", rate: 36, qty: [2000, 20000] },
      { name: "Hydrochloric acid 33%", alias: ["hcl", "acid"], unit: "kg", rate: 11, qty: [5000, 30000] },
      { name: "Isopropyl alcohol", alias: ["ipa", "isopropyl"], unit: "kg", rate: 118, qty: [500, 5000] },
      { name: "Acetone", alias: ["acetone"], unit: "kg", rate: 96, qty: [500, 5000] },
      { name: "Sodium hypochlorite", alias: ["hypo", "hypochlorite"], unit: "kg", rate: 19, qty: [2000, 15000] },
    ],
  },
  {
    id: "pharma",
    label: "Pharma distribution",
    note: "Batches, expiry and many small bills",
    terms: "Cold chain where needed · batch on invoice",
    expiry: true,
    customerKinds: ["Medicals", "Pharmacy", "Hospital", "Healthcare", "Chemists", "Clinic"],
    suppliers: [
      { name: "Cipla C&F", brand: "Cipla" },
      { name: "Sun Pharma C&F", brand: "Sun" },
      { name: "Alkem depot", brand: "Alkem" },
      { name: "Mankind C&F", brand: "Mankind" },
    ],
    products: [
      { name: "Paracetamol 650 (10×15)", alias: ["paracetamol", "pcm", "650"], unit: "box", rate: 285, qty: [50, 400] },
      { name: "Amoxicillin 500 (10×10)", alias: ["amoxicillin", "amox"], unit: "box", rate: 612, qty: [20, 200] },
      { name: "Pantoprazole 40 (10×15)", alias: ["pantoprazole", "pan"], unit: "box", rate: 430, qty: [30, 300] },
      { name: "Metformin 500 (10×20)", alias: ["metformin"], unit: "box", rate: 198, qty: [50, 400] },
      { name: "Azithromycin 500 (10×3)", alias: ["azithromycin", "azee"], unit: "box", rate: 705, qty: [20, 150] },
      { name: "ORS sachets (box of 50)", alias: ["ors"], unit: "box", rate: 420, qty: [20, 200] },
    ],
  },
  {
    id: "auto",
    label: "Auto parts",
    note: "OEM part numbers and fitment",
    terms: "Ex-godown · 6-month warranty",
    customerKinds: ["Motors", "Auto Garage", "Service Centre", "Spares", "Automobiles", "Transport"],
    suppliers: [
      { name: "Bosch distributor", brand: "Bosch" },
      { name: "Minda CFA", brand: "Minda" },
      { name: "Rane dealer", brand: "Rane" },
      { name: "Gabriel stockist", brand: "Gabriel" },
    ],
    products: [
      { name: "Brake pad set (front)", alias: ["brake", "pad"], unit: "set", rate: 1450, qty: [20, 200] },
      { name: "Clutch plate", alias: ["clutch"], unit: "pc", rate: 2350, qty: [10, 120] },
      { name: "Oil filter", alias: ["filter", "oil filter"], unit: "pc", rate: 185, qty: [100, 800] },
      { name: "Headlamp assembly", alias: ["headlamp", "headlight"], unit: "pc", rate: 3200, qty: [10, 80] },
      { name: "Spark plug", alias: ["spark", "plug"], unit: "pc", rate: 160, qty: [100, 1000] },
      { name: "Shock absorber (rear)", alias: ["shock", "absorber"], unit: "pc", rate: 2850, qty: [10, 100] },
    ],
  },
  {
    id: "packaging",
    label: "Packaging",
    note: "Custom sizes priced by weight",
    terms: "Delivered · printing extra",
    customerKinds: ["Foods", "Exports", "Industries", "Logistics", "Pharma", "Retail"],
    suppliers: [
      { name: "Uflex dealer", brand: "Uflex" },
      { name: "Cosmo Films CFA", brand: "Cosmo" },
      { name: "TCPL stockist", brand: "TCPL" },
      { name: "Local board mill", brand: "Mill" },
    ],
    products: [
      { name: "Corrugated box 5-ply", alias: ["box", "carton", "corrugated"], unit: "pc", rate: 38, qty: [2000, 20000] },
      { name: "Stretch film roll 23µ", alias: ["stretch", "film"], unit: "roll", rate: 420, qty: [50, 600] },
      { name: "BOPP tape 48mm", alias: ["tape", "bopp"], unit: "roll", rate: 42, qty: [500, 5000] },
      { name: "Bubble wrap roll", alias: ["bubble"], unit: "roll", rate: 890, qty: [20, 200] },
      { name: "HDPE bag 50kg", alias: ["hdpe", "bag"], unit: "pc", rate: 9, qty: [5000, 50000] },
      { name: "Paper core 3\"", alias: ["core"], unit: "pc", rate: 22, qty: [1000, 8000] },
    ],
  },
  {
    id: "textiles",
    label: "Textiles & fabrics",
    note: "Long credit and agents",
    terms: "Ex-godown · 90-day credit standard",
    customerKinds: ["Garments", "Fashions", "Exports", "Textiles", "Creations", "Apparel"],
    suppliers: [
      { name: "Arvind mill depot", brand: "Arvind" },
      { name: "Vardhman agent", brand: "Vardhman" },
      { name: "Surat weaver", brand: "Surat" },
      { name: "Bhiwandi mill", brand: "Bhiwandi" },
    ],
    products: [
      { name: "Cotton poplin 58\"", alias: ["cotton", "poplin"], unit: "m", rate: 78, qty: [2000, 15000] },
      { name: "Polyester georgette", alias: ["georgette", "polyester"], unit: "m", rate: 64, qty: [2000, 15000] },
      { name: "Denim 12 oz", alias: ["denim"], unit: "m", rate: 185, qty: [1000, 8000] },
      { name: "Rayon print", alias: ["rayon"], unit: "m", rate: 92, qty: [2000, 12000] },
      { name: "Linen blend", alias: ["linen"], unit: "m", rate: 240, qty: [500, 4000] },
      { name: "Lycra knit", alias: ["lycra", "knit"], unit: "kg", rate: 410, qty: [200, 2000] },
    ],
  },
  {
    id: "agri",
    label: "Agri inputs",
    note: "Seasonal credit, collections after harvest",
    terms: "Delivered to dealer · season credit",
    customerKinds: ["Krishi Kendra", "Agro", "Seeds", "Fertilisers", "Agri Traders", "FPO"],
    suppliers: [
      { name: "IFFCO depot", brand: "IFFCO" },
      { name: "Coromandel CFA", brand: "Coromandel" },
      { name: "UPL distributor", brand: "UPL" },
      { name: "Mahyco dealer", brand: "Mahyco" },
    ],
    products: [
      { name: "Urea 45kg", alias: ["urea"], unit: "bag", rate: 267, qty: [200, 2000] },
      { name: "DAP 50kg", alias: ["dap"], unit: "bag", rate: 1350, qty: [100, 1000] },
      { name: "NPK 19:19:19 (1kg)", alias: ["npk"], unit: "pack", rate: 135, qty: [200, 2000] },
      { name: "Hybrid maize seed 4kg", alias: ["seed", "maize"], unit: "pack", rate: 1480, qty: [50, 400] },
      { name: "Insecticide 1L", alias: ["pesticide", "insecticide"], unit: "bottle", rate: 640, qty: [50, 500] },
      { name: "Drip lateral 16mm", alias: ["drip", "lateral"], unit: "m", rate: 7, qty: [5000, 40000] },
    ],
  },
  {
    id: "lubricants",
    label: "Lubricants",
    note: "Brand and pack size matter",
    terms: "Delivered · drums returnable",
    customerKinds: ["Transport", "Industries", "Motors", "Logistics", "Engineering", "Fleet"],
    suppliers: [
      { name: "Castrol distributor", brand: "Castrol" },
      { name: "Servo CFA", brand: "Servo" },
      { name: "Gulf Oil dealer", brand: "Gulf" },
      { name: "Shell stockist", brand: "Shell" },
    ],
    products: [
      { name: "Engine oil 15W40 (210 L)", alias: ["15w40", "engine oil", "diesel oil"], unit: "barrel", rate: 38500, qty: [4, 40] },
      { name: "Hydraulic oil 68 (210 L)", alias: ["hydraulic"], unit: "barrel", rate: 31800, qty: [4, 30] },
      { name: "Gear oil 90 (210 L)", alias: ["gear"], unit: "barrel", rate: 34200, qty: [2, 20] },
      { name: "Grease MP3 (18 kg)", alias: ["grease"], unit: "bucket", rate: 4250, qty: [10, 80] },
      { name: "Engine oil 20W50 (5 L)", alias: ["20w50"], unit: "can", rate: 1650, qty: [50, 400] },
      { name: "Coolant (5 L)", alias: ["coolant"], unit: "can", rate: 720, qty: [50, 300] },
    ],
  },
  {
    id: "mro",
    label: "Industrial / MRO",
    note: "Part numbers and urgent breakdowns",
    terms: "Ex-stock · same-day dispatch",
    customerKinds: ["Industries", "Forgings", "Engineering", "Plastics", "Auto Comp", "Works"],
    suppliers: [
      { name: "SKF distributor", brand: "SKF" },
      { name: "Fenner dealer", brand: "Fenner" },
      { name: "Ador stockist", brand: "Ador" },
      { name: "Karam CFA", brand: "Karam" },
    ],
    products: [
      { name: "Bearing 6205-2Z", alias: ["bearing", "6205"], unit: "pc", rate: 185, qty: [100, 1000] },
      { name: "V-belt B-52", alias: ["belt", "v-belt"], unit: "pc", rate: 260, qty: [50, 400] },
      { name: "Hydraulic hose 1/2\"", alias: ["hose"], unit: "m", rate: 340, qty: [50, 400] },
      { name: "Welding electrode 3.15mm", alias: ["electrode", "welding"], unit: "pkt", rate: 520, qty: [50, 400] },
      { name: "Safety shoes", alias: ["shoes", "safety"], unit: "pair", rate: 780, qty: [50, 300] },
      { name: "Cutting wheel 14\"", alias: ["cutting", "wheel"], unit: "pc", rate: 210, qty: [100, 800] },
    ],
  },
];

export function industryById(id: string): IndustryPack {
  return INDUSTRIES.find((i) => i.id === id) ?? (INDUSTRIES[0] as IndustryPack);
}
