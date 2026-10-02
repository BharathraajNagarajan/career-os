import { useSearchParams } from "react-router-dom";

import { NOTICES, signInErrorMessage } from "./signInMessages";

export function SignIn() {
  const [params] = useSearchParams();
  const error = signInErrorMessage(params.get("error"));
  const noticeCode = params.get("notice");
  const notice = noticeCode === null ? null : (NOTICES[noticeCode] ?? null);

  return (
    <section aria-labelledby="sign-in-title">
      <h1 id="sign-in-title">Sign in</h1>
      {error !== null && <p role="alert">{error}</p>}
      {notice !== null && <p role="status">{notice}</p>}
      <p>
        <a href="/api/v1/auth/google/start?return_to=/">Sign in with Google</a>
      </p>
    </section>
  );
}
