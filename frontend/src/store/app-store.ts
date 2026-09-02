import { create } from "zustand";
import { AppState } from "../types";
import type { SelectedElement } from "../components/preview/previewMessaging";

// Store for app-wide state
interface AppStore {
  appState: AppState;
  setAppState: (state: AppState) => void;

  // UI state
  updateInstruction: string;
  setUpdateInstruction: (instruction: string) => void;

  // Update images support (multiple images)
  updateImages: string[];
  setUpdateImages: (images: string[]) => void;

  inSelectAndEditMode: boolean;
  toggleInSelectAndEditMode: () => void;
  disableInSelectAndEditMode: () => void;

  // A serialized snapshot of the element the user picked in the (sandboxed)
  // preview — never a live cross-frame DOM node.
  selectedElement: SelectedElement | null;
  setSelectedElement: (element: SelectedElement | null) => void;
  clearSelectedElement: () => void;
}

export const useAppStore = create<AppStore>((set) => ({
  appState: AppState.INITIAL,
  setAppState: (state: AppState) => set({ appState: state }),

  // UI state
  updateInstruction: "",
  setUpdateInstruction: (instruction: string) =>
    set({ updateInstruction: instruction }),

  // Update images support
  updateImages: [],
  setUpdateImages: (images: string[]) => set({ updateImages: images }),

  inSelectAndEditMode: false,
  toggleInSelectAndEditMode: () =>
    set((state) =>
      state.inSelectAndEditMode
        ? { inSelectAndEditMode: false, selectedElement: null }
        : { inSelectAndEditMode: true }
    ),
  // Exiting selection mode and releasing its locked target are one action.
  // Keeping this atomic prevents a stale selection from surviving a version
  // change until PreviewComponent's effects get a chance to run.
  disableInSelectAndEditMode: () =>
    set({ inSelectAndEditMode: false, selectedElement: null }),

  selectedElement: null,
  setSelectedElement: (element: SelectedElement | null) =>
    set({ selectedElement: element }),
  clearSelectedElement: () => set({ selectedElement: null }),
}));
