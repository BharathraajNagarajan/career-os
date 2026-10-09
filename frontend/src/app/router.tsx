import { createBrowserRouter } from "react-router-dom";

import { Actions } from "../routes/Actions";
import { Applications } from "../routes/Applications";
import { Companies } from "../routes/Companies";
import { ContactDetail } from "../routes/ContactDetail";
import { Contacts } from "../routes/Contacts";
import { HomePlaceholder } from "../routes/HomePlaceholder";
import { Lanes } from "../routes/Lanes";
import { OpportunityDetail } from "../routes/OpportunityDetail";
import { Opportunities } from "../routes/Opportunities";
import { Profile } from "../routes/Profile";
import { Resumes } from "../routes/Resumes";
import { Review } from "../routes/Review";
import { Settings } from "../routes/Settings";
import { SignIn } from "../routes/SignIn";
import { StrategyRules } from "../routes/StrategyRules";
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
          { path: "opportunities", element: <Opportunities /> },
          { path: "opportunities/:opportunityId", element: <OpportunityDetail /> },
          { path: "applications", element: <Applications /> },
          { path: "companies", element: <Companies /> },
          { path: "contacts", element: <Contacts /> },
          { path: "contacts/:contactId", element: <ContactDetail /> },
          { path: "actions", element: <Actions /> },
          { path: "rules", element: <StrategyRules /> },
          { path: "review", element: <Review /> },
          { path: "settings", element: <Settings /> },
        ],
      },
    ],
  },
]);
