import { render, screen, within } from "@testing-library/react";
import { MemoryRouter } from "react-router-dom";

import { Layout } from "./Layout";

describe("Layout", () => {
  it("shows the product name and the creator attribution", () => {
    render(
      <MemoryRouter>
        <Layout />
      </MemoryRouter>,
    );

    expect(screen.getByText("Career OS")).toBeInTheDocument();
    expect(screen.getByText("Created by Bharathraaj Nagarajan")).toBeInTheDocument();
  });

  it("links to every signed-in section", () => {
    render(
      <MemoryRouter>
        <Layout />
      </MemoryRouter>,
    );

    const nav = screen.getByRole("navigation", { name: "Main" });
    const links = within(nav)
      .getAllByRole("link")
      .map((link) => [link.textContent, link.getAttribute("href")]);

    expect(links).toEqual([
      ["Profile", "/profile"],
      ["Resumes", "/resumes"],
      ["Lanes", "/lanes"],
      ["Review", "/review"],
      ["Settings", "/settings"],
    ]);
  });
});
