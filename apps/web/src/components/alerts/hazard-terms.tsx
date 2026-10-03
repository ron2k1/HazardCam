import { Fragment } from "react";

// Words that name the hazard, the thing causing it or the rule it breaks (longest phrases first,
// so "trip hazard" lights up as one phrase instead of two words).
const TERMS =
  /\b(trip(?:ping)? hazards?|slip(?:ping)? hazards?|fall hazards?|struck-by|crush(?:ing)? hazards?|loose (?:materials?|objects?|items?|debris)|(?:circular )?metal (?:objects?|coils?|shavings)|trip(?:ping|s)?|slip(?:ping|s|pery)?|falling|crush(?:ing)?|pinch(?:ing)?|collisions?|hazards?|hazardous|loose|debris|shavings|scrap|coils?|hoses?|cables?|spills?|forklifts?|overload(?:ed|ing)?|obstruct(?:s|ed|ing|ion)?|block(?:ed|ing|s)|unsecured|unstable)\b/gi;

/** Plain text with the hazard words in red, so the reader sees what and why at a glance. */
export function HazardText({ text }: { text: string }) {
  const parts = text.split(TERMS);
  return (
    <>
      {parts.map((part, i) =>
        i % 2 === 1 ? (
          <strong key={i} className="font-semibold text-danger" data-testid="hazard-term">
            {part}
          </strong>
        ) : (
          <Fragment key={i}>{part}</Fragment>
        ),
      )}
    </>
  );
}
