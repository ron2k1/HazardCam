import { Fragment } from "react";

// Two tiers of emphasis. Red: the hazard, what causes it, the harm it does. Bold white: who is at
// risk, where, and the equipment involved. Phrases come before single words in the alternation so
// "trip hazard" or "blind corner" lights up as one phrase instead of two words.
const RED_PHRASES = [
  "trip(?:ping)? hazards?",
  "slip(?:ping)? hazards?",
  "fall hazards?",
  "crush(?:ing)? hazards?",
  "struck[- ]by",
  "caught[- ]in",
  "pinch points?",
  "near[- ]miss(?:es)?",
  "blind (?:spots?|corners?)",
  "loose (?:materials?|objects?|items?|debris|parts?)",
  "(?:circular )?metal (?:objects?|coils?|shavings|parts?)",
  "sharp (?:edges?|objects?)",
  "wet floors?",
  "tip(?:ping)? over",
];
const KEY_PHRASES = [
  "walking[- ]working surfaces?",
  "walking surfaces?",
  "work(?:ing)? areas?",
  "travel (?:paths?|lanes?)",
  "emergency exits?",
  "eye protection",
  "safety glasses",
  "hard hats?",
  "zone \\d+",
];
const RED_WORDS = [
  "trip(?:ping|s)?",
  "slip(?:ping|s|pery)?",
  "falling",
  "crush(?:ed|ing)?",
  "pinch(?:ed|ing)?",
  "struck",
  "collisions?",
  "hazards?",
  "hazardous",
  "danger(?:ous)?",
  "unsafe",
  "loose",
  "debris",
  "shavings",
  "scrap",
  "clutter(?:ed)?",
  "coils?",
  "hoses?",
  "cables?",
  "cords?",
  "spills?",
  "leaks?",
  "forklifts?",
  "overload(?:ed|ing)?",
  "obstruct(?:s|ed|ing|ions?)?",
  "block(?:ed|ing|s)",
  "unsecured",
  "unstable",
  "unguarded",
  "exposed",
  "injur(?:y|ies|ed)",
  "congest(?:ed|ion)",
  "protruding",
  "uneven",
];
const KEY_WORDS = [
  "workers?",
  "operators?",
  "pedestrians?",
  "people",
  "personnel",
  "employees?",
  "walkways?",
  "aisles?",
  "floors?",
  "paths?",
  "exits?",
  "stairs?",
  "machines?",
  "machinery",
  "equipment",
  "pallets?",
  "loads?",
  "racks?",
  "racking",
  "shelving",
  "vehicles?",
  "carts?",
  "bins?",
  "PPE",
  "gloves",
  "guards?",
  "guardrails?",
  "intersections?",
  "corners?",
  "clearance",
];

const TERMS = new RegExp(`\\b(${[...RED_PHRASES, ...KEY_PHRASES, ...RED_WORDS, ...KEY_WORDS].join("|")})\\b`, "gi");
const RED = new RegExp(`^(?:${[...RED_PHRASES, ...RED_WORDS].join("|")})$`, "i");

/** Plain text with the hazard words in red and the people, places and equipment in bold. */
export function HazardText({ text }: { text: string }) {
  const parts = text.split(TERMS);
  return (
    <>
      {parts.map((part, i) =>
        i % 2 === 0 ? (
          <Fragment key={i}>{part}</Fragment>
        ) : RED.test(part) ? (
          <strong key={i} className="font-semibold text-danger" data-testid="hazard-term">
            {part}
          </strong>
        ) : (
          <strong key={i} className="font-bold text-fg" data-testid="key-term">
            {part}
          </strong>
        ),
      )}
    </>
  );
}
