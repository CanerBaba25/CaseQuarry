import english from "./catalogs/en.json";

export const locales = [
  { code: "en", nativeName: "English", intl: "en-US" },
  { code: "ru", nativeName: "Русский", intl: "ru-RU" },
  { code: "fr", nativeName: "Français", intl: "fr-FR" },
  { code: "es", nativeName: "Español", intl: "es-ES" },
  { code: "de", nativeName: "Deutsch", intl: "de-DE" },
  { code: "tr", nativeName: "Türkçe", intl: "tr-TR" },
  { code: "el", nativeName: "Ελληνικά", intl: "el-GR" },
  { code: "it", nativeName: "Italiano", intl: "it-IT" },
  { code: "pt", nativeName: "Português", intl: "pt-PT" },
  { code: "uk", nativeName: "Українська", intl: "uk-UA" },
  { code: "zh-Hans", nativeName: "简体中文", intl: "zh-Hans" },
  { code: "zh-Hant", nativeName: "繁體中文", intl: "zh-Hant" },
  { code: "hi", nativeName: "हिन्दी", intl: "hi-IN" },
] as const;
export type Language = (typeof locales)[number]["code"];
export type MessageKey = keyof typeof english;
export type Catalog = Partial<Record<MessageKey, string>> &
  Record<string, string | undefined>;
export type MessageValues = Readonly<Record<string, string | number>>;
export function isMessageKey(value: string): value is MessageKey {
  return Object.prototype.hasOwnProperty.call(english, value);
}

export function normalizeLanguage(value: unknown): Language {
  return locales.find((locale) => locale.code === value)?.code || "en";
}
export function intlLocale(language: Language): string {
  return locales.find((locale) => locale.code === language)!.intl;
}

const loaders = {
  en: () => Promise.resolve({ default: english }),
  ru: () => import("./catalogs/ru.json"),
  fr: () => import("./catalogs/fr.json"),
  es: () => import("./catalogs/es.json"),
  de: () => import("./catalogs/de.json"),
  tr: () => import("./catalogs/tr.json"),
  el: () => import("./catalogs/el.json"),
  it: () => import("./catalogs/it.json"),
  pt: () => import("./catalogs/pt.json"),
  uk: () => import("./catalogs/uk.json"),
  "zh-Hans": () => import("./catalogs/zh-Hans.json"),
  "zh-Hant": () => import("./catalogs/zh-Hant.json"),
  hi: () => import("./catalogs/hi.json"),
};
export async function loadCatalog(language: Language): Promise<Catalog> {
  return (await loaders[language]()).default;
}

// Call only for interface-authored messages; evidence and user text stay original.
export function createTranslator(language: Language, catalog: Catalog = {}) {
  const numbers = new Intl.NumberFormat(intlLocale(language));
  return (message: string, values: MessageValues = {}): string => {
    const translated = Object.prototype.hasOwnProperty.call(catalog, message)
      ? catalog[message]
      : undefined;
    const fallback = isMessageKey(message) ? english[message] : undefined;
    const pattern =
      typeof translated === "string" && translated.length
        ? translated
        : typeof fallback === "string"
          ? fallback
          : message;
    return pattern.replace(/\{(\w+)\}/g, (placeholder, key: string) => {
      const value = Object.prototype.hasOwnProperty.call(values, key)
        ? values[key]
        : undefined;
      return value === undefined
        ? placeholder
        : typeof value === "number"
          ? numbers.format(value)
          : value;
    });
  };
}
