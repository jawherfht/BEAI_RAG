import { redirect } from "next/navigation";
import { randomUUID } from "node:crypto";

/** Dev entry point: opens screen B for a fresh agent id. */
export default function Home() {
  redirect(`/agents/${randomUUID()}/knowledge-base`);
}
