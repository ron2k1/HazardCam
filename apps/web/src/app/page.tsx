import { redirect } from "next/navigation";

// Safety hazards is the main product screen; the multi-camera console stays at /ops.
export default function LandingPage() {
  redirect("/hazards");
}
