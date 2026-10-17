import { redirect } from "next/navigation";
import { randomUUID } from "node:crypto";

export const dynamic = "force-dynamic";

const UUID = /^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$/i;

/** Dev entry point: opens screen B for DEV_AGENT_ID (local Docker mode) or a fresh agent id. */
export default function Home() {
  const fixed = process.env.DEV_AGENT_ID;
  redirect(`/agents/${fixed && UUID.test(fixed) ? fixed : randomUUID()}/knowledge-base`);
}
