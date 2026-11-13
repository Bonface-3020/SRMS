const search=document.querySelector("#search");
if(search){
    search.addEventListener("input",()=>{
        let matches=0
        document.querySelectorAll(".resource").forEach(card=>{
            const visible=card.dataset.search.includes(search.value.trim().toLowerCase());
            card.hidden = !visible;
            if (visible) matches++;
        })
        document.querySelector('#no-results').hidden = matches > 0;
    })
}