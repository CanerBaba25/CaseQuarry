import {
  createTranslator,
  intlLocale,
  isMessageKey,
  type Catalog,
  type Language,
  type MessageValues,
  type MessageKey,
} from "../../../../packages/i18n";

let language: Language = "en";
let translate = createTranslator("en");
export type InterfaceMessage =
  "" | MessageKey | Readonly<{ message: MessageKey; values: MessageValues }>;

export function setInterfaceCatalog(next: Language, catalog: Catalog) {
  language = next;
  translate = createTranslator(next, catalog);
}
export function getInterfaceLanguage(): Language {
  return language;
}
export function getInterfaceLocale(): string {
  return intlLocale(language);
}
// Only interface-authored messages belong here; original evidence stays original.
export function uiText(
  message: InterfaceMessage | "",
  values?: MessageValues,
): string {
  return typeof message === "string"
    ? translate(message, values)
    : translate(message.message, message.values);
}
export function uiMessage(
  message: MessageKey,
  values: MessageValues,
): InterfaceMessage {
  return { message, values };
}
// Unknown API diagnostics and machine metadata retain their original spelling.
export function uiKnownText(message: string): string {
  return isMessageKey(message) ? uiText(message) : message;
}

export type { MessageKey } from "../../../../packages/i18n";
