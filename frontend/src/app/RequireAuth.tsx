import { useQuery } from "@tanstack/react-query";
import { Navigate, Outlet } from "react-router-dom";

import { fetchMe } from "../api/auth";
import { ApiRequestError, SIGN_IN_PATH } from "../api/client";

export function RequireAuth() {
  const me = useQuery({
    queryKey: ["me"],
    queryFn: ({ signal }) => fetchMe(signal),
    retry: false,
  });

  if (me.isPending) {
    return <p role="status">Checking your session…</p>;
  }
  if (me.isError) {
    if (me.error instanceof ApiRequestError && me.error.status === 401) {
      return <Navigate to={SIGN_IN_PATH} replace />;
    }
    return <p role="alert">Could not reach the API. Start the backend and reload.</p>;
  }
  return <Outlet />;
}
