import { render, screen } from "@testing-library/react";
import { MemoryRouter } from "react-router-dom";

import { SignIn } from "./SignIn";

function renderAt(search: string) {
  return render(
    <MemoryRouter initialEntries={[`/sign-in${search}`]}>
      <SignIn />
    </MemoryRouter>,
  );
}

describe("SignIn", () => {
  it("links to the Google sign-in start endpoint", () => {
    renderAt("");

    expect(screen.getByRole("link", { name: "Sign in with Google" })).toHaveAttribute(
      "href",
      "/api/v1/auth/google/start?return_to=/",
    );
    expect(screen.queryByRole("alert")).not.toBeInTheDocument();
  });

  it("explains an account conflict in plain language", () => {
    renderAt("?error=account_conflict");

    expect(screen.getByRole("alert")).toHaveTextContent("already exists");
  });

  it("falls back to a generic message for unknown error codes", () => {
    renderAt("?error=something_unexpected_and_detailed");

    expect(screen.getByRole("alert")).toHaveTextContent("Sign-in failed. Please try again.");
    expect(screen.getByRole("alert")).not.toHaveTextContent("something_unexpected");
  });
});
