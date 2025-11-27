// 모달 열기 함수
function openModal(id) {
    const modal = document.getElementById(id);
    if (modal) {
        modal.classList.add('active');
    }
}

// 모달 닫기 함수
function closeModal(id) {
    const modal = document.getElementById(id);
    if (modal) {
        modal.classList.remove('active');
    }
}

// 모달 오버레이 클릭 시 닫기 이벤트 리스너
document.addEventListener('DOMContentLoaded', () => {
    document.querySelectorAll('.modal-overlay').forEach(overlay => {
        overlay.addEventListener('click', function(e) {
            // 클릭된 요소가 오버레이 자체인지 확인
            if (e.target === this) {
                this.classList.remove('active');
            }
        });
    });
});