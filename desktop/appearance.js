"use strict";
const appearance=(()=>{
  const themes=["system","light","dark"],sizes=["small","medium","large"];
  const saved=(key,values)=>values.includes(localStorage.getItem(key))?localStorage.getItem(key):values[0];
  let theme=saved("theme",themes),size=saved("uiSize",sizes);
  function paint(effective){
    document.documentElement.dataset.theme=theme==="system"?effective:theme;
  }
  function apply(){
    if(theme!=="system")paint(theme);
    return window.desktop.appearance(theme,size);
  }
  paint(matchMedia("(prefers-color-scheme: dark)").matches?"dark":"light");
  window.desktop.onThemeChanged(paint);
  apply();
  return {
    get theme(){return theme;},
    get size(){return size;},
    set(nextTheme,nextSize){
      if(!themes.includes(nextTheme)||!sizes.includes(nextSize))return;
      theme=nextTheme;size=nextSize;
      localStorage.setItem("theme",theme);localStorage.setItem("uiSize",size);
      return apply();
    }
  };
})();
