import { createBrowserRouter } from "react-router-dom";

import { HomePlaceholder } from "../routes/HomePlaceholder";
import { Layout } from "./Layout";

export const router = createBrowserRouter([
  {
    path: "/",
    element: <Layout />,
    children: [{ index: true, element: <HomePlaceholder /> }],
  },
]);
