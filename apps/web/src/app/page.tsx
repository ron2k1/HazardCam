import type { Metadata } from "next";

import { SiteWall } from "@/components/wall/site-wall";

export const metadata: Metadata = {
  title: "Site cameras · CameraVision",
};

/**
 * "/" — the CameraVision home screen: one wall of site cameras. CAM 1-3 watch for hazards on the
 * factory floor, CAM 4-6 watch warehouse blind spots. Which clips appear is configuration
 * (config/wall.yaml via GET /api/wall); results come only from checks that complete here.
 */
export default function HomePage() {
  return <SiteWall />;
}
