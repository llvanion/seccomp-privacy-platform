import { Link, isRouteErrorResponse, useRouteError } from "react-router-dom";
import { Button, ErrorBanner } from "./ui";

export function ErrorBoundary() {
  const error = useRouteError() as unknown;
  let title = "出错了";
  let message: string = "An unexpected error occurred while rendering this view.";
  if (isRouteErrorResponse(error)) {
    title = `${error.status} ${error.statusText}`;
    if (typeof error.data === "string") message = error.data;
  } else if (error instanceof Error) {
    message = error.message;
  }

  return (
    <div className="min-h-screen p-10 grid place-items-center">
      <div className="max-w-xl w-full space-y-4">
        <ErrorBanner title={title} message={message} />
        <div className="flex items-center gap-2">
          <Link to="/home" className="focus-ring rounded">
            <Button variant="secondary">回首页</Button>
          </Link>
          <Button variant="ghost" onClick={() => window.location.reload()}>
            重载
          </Button>
        </div>
      </div>
    </div>
  );
}
