"use client";

import { useCallback, useEffect, useState } from "react";

export type UiLanguage = "pl" | "en";

const STORAGE_KEY = "pulsai:ui-language";

export function uiText(language: UiLanguage, polish: string, english: string): string {
  return language === "pl" ? polish : english;
}

export function useUiLanguage() {
  const [language, setLanguageState] = useState<UiLanguage>("pl");

  useEffect(() => {
    const stored = window.localStorage.getItem(STORAGE_KEY);
    const initial: UiLanguage =
      stored === "pl" || stored === "en"
        ? stored
        : window.navigator.language.toLowerCase().startsWith("pl")
          ? "pl"
          : "en";
    setLanguageState(initial);
    document.documentElement.lang = initial;
  }, []);

  const setLanguage = useCallback((next: UiLanguage) => {
    setLanguageState(next);
    window.localStorage.setItem(STORAGE_KEY, next);
    document.documentElement.lang = next;
  }, []);

  return { language, setLanguage };
}

