import { createBrowserRouter } from "react-router-dom";

import { HomePlaceholder } from "../routes/HomePlaceholder";
import { Lanes } from "../routes/Lanes";
import { Profile } from "../routes/Profile";
import { Resumes } from "../routes/Resumes";
import { Settings } from "../routes/Settings";
import { SignIn } from "../routes/SignIn";
import { Layout } from "./Layout";
import { RequireAuth } from "./RequireAuth";

export const router = createBrowserRouter([
  {
    path: "/",
    element: <Layout />,
    children: [
      { path: "sign-in", element: <SignIn /> },
      {
        element: <RequireAuth />,
        children: [
          { index: true, element: <HomePlaceholder /> },
          { path: "profile", element: <Profile /> },
          { path: "resumes", element: <Resumes /> },
          { path: "lanes", element: <Lanes /> },
          { path: "settings", element: <Settings /> },
        ],
      },
    ],
  },
]);
