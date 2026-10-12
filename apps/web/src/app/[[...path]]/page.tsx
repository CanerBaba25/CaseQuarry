import Workspace from "@/components/workspace";
import { Suspense } from "react";

export default function Page() {
  return (
    <Suspense
      fallback={
        <div className="boot" role="status">
          Opening workspace…
        </div>
      }
    >
      <Workspace />
    </Suspense>
  );
}
