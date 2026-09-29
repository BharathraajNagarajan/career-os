import { render, screen } from "@testing-library/react";
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
});
