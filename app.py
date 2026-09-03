"""
Shelf Audit Tool - minimal working slice.
 
Goal of this file: prove the core loop works (photo -> API -> useful results)
before adding database, history, or a criteria editor. Keep this dumb on purpose.
"""
import streamlit as st
 
st.set_page_config(page_title="Shelf Audit Tool", page_icon="\U0001F4F8")
st.title("Shelf Audit Tool")
st.caption("Take a shelf photo at approximately eye level (~60 inches) to get audit suggestions.")
 
photo = st.camera_input("Shelf photo")
 
if photo is not None:
    criteria = load_criteria()
 
    with st.spinner("Analyzing photo..."):
        try:
            results = evaluate_photo(photo.getvalue(), criteria)
        except ValueError as e:
            st.error(f"Something went wrong parsing the model's response: {e}")
            st.stop()
        except Exception as e:
            st.error(f"API call failed: {e}")
            st.stop()
 
    st.divider()
    st.subheader("Results")
 
    applicable = [r for r in results if r.applies]
    not_applicable = [r for r in results if not r.applies]
 
    if not applicable:
        st.info("No criteria were flagged as applicable to this photo.")
 
    for r in applicable:
        icon = "✅" if r.met else "❌"
        st.markdown(f"{icon} **{r.id}**")
        st.caption(f"Evidence: {r.evidence}")
        if r.suggestion:
            st.markdown(f"💡 {r.suggestion}")
        st.write("")
 
    if not_applicable:
        with st.expander(f"Not applicable to this photo ({len(not_applicable)})"):
            for r in not_applicable:
                st.write(f"- {r.id}")
 